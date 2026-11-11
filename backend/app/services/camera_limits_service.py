# backend/app/services/camera_limits_service.py
"""
Dynamic Camera Limits Discovery & Three-Zone Controls Engine.

Finds a camera's real control limits instead of hardcoding them.
Resolution order, per control, first hit wins:
    1. Cache        earlier probe results for this (platform, sensor, socket)
    2. Live probe   ask the running camera what it accepts (see LiveServiceProbeBackend)
    3. Profile      measured values for known sensors (PROFILES)
    4. API contract conservative documented values for unknown sensors

Every Range indicates its origin (`source`) and whether the bound was actually
verified on hardware (`verified`).
Recommended zones are derived dynamically by RecommendedPolicy.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import time
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Optional, Protocol
from sqlalchemy import text

logger = logging.getLogger("camera-limits")

SCHEMA_VERSION = 2
STANDARD_FPS = (5, 10, 15, 20, 25, 30, 60)
DEFAULT_EXPOSURE_CEILING_US = 1_000_000


# --------------------------------------------------------------------------- #
# Data Model
# --------------------------------------------------------------------------- #
class Source(str, Enum):
    PROBED = "probed"
    PROFILE = "profile"
    API_CONTRACT = "api_contract"
    APP_DEFINED = "app_defined"


@dataclass(frozen=True)
class Range:
    min: float
    max: float
    source: Source
    verified: bool = True
    note: str = ""

    def clamp(self, v: float) -> float:
        return max(self.min, min(self.max, v))


@dataclass(frozen=True)
class StreamMode:
    width: int
    height: int
    min_fps: float
    max_fps: float


@dataclass(frozen=True)
class CameraIdentity:
    platform: str
    sensor: str
    socket: str
    has_autofocus: bool
    stream_modes: tuple[StreamMode, ...] = ()

    @property
    def key(self) -> str:
        return f"{self.platform}|{self.sensor}|{self.socket}"


@dataclass(frozen=True)
class RecommendedPolicy:
    gain_base: float = 100.0
    gain_stops_over_base: float = 6.0     # 100 -> 6400 on typical sensor
    exposure_fps_fraction: float = 0.95   # stay under frame period (95%)
    comfort_fraction: float = 0.4         # +/- share of half-range for tone controls


@dataclass
class CameraLimits:
    identity: CameraIdentity
    gain: Range
    exposure_us: Range
    focus: Optional[Range]                # None = no autofocus motor
    brightness: Range
    contrast: Range

    def exposure_max_for_fps(self, fps: float) -> float:
        return min(self.exposure_us.max, 1_000_000.0 / fps)

    def fps_options(self, width: int, height: int) -> list[int]:
        for m in self.identity.stream_modes:
            if (m.width, m.height) == (width, height):
                return [f for f in STANDARD_FPS if m.min_fps <= f <= m.max_fps]
        return list(STANDARD_FPS)

    def recommended(self, fps: float, p: RecommendedPolicy = RecommendedPolicy()) -> dict[str, Range]:
        base = max(self.gain.min, p.gain_base)
        rec_exp_max = min(self.exposure_us.max, (1_000_000.0 / fps) * p.exposure_fps_fraction)
        zones = {
            "gain": Range(base, min(self.gain.max, base * (2 ** p.gain_stops_over_base)), Source.PROFILE),
            "exposure_us": Range(self.exposure_us.min, rec_exp_max, Source.PROFILE),
            "brightness": _central(self.brightness, p.comfort_fraction),
            "contrast": _central(self.contrast, p.comfort_fraction),
        }
        if self.focus:
            zones["focus"] = self.focus
        return zones

    def to_dict(self) -> dict:
        d = asdict(self)
        d["schema"] = SCHEMA_VERSION
        return json.loads(json.dumps(d, default=lambda o: o.value if isinstance(o, Enum) else str(o)))

    @staticmethod
    def from_dict(d: dict) -> "CameraLimits":
        def rng(x):
            return None if x is None else Range(
                float(x["min"]),
                float(x["max"]),
                Source(x["source"]),
                bool(x.get("verified", True)),
                str(x.get("note", ""))
            )
        i = d["identity"]
        ident = CameraIdentity(
            str(i["platform"]),
            str(i["sensor"]),
            str(i["socket"]),
            bool(i["has_autofocus"]),
            tuple(StreamMode(**m) for m in i.get("stream_modes", []))
        )
        return CameraLimits(
            ident,
            rng(d["gain"]),
            rng(d["exposure_us"]),
            rng(d.get("focus")),
            rng(d["brightness"]),
            rng(d["contrast"])
        )


def _central(r: Range, frac: float) -> Range:
    mid, half = (r.min + r.max) / 2.0, (r.max - r.min) / 2.0
    return Range(mid - half * frac, mid + half * frac, Source.PROFILE)


# --------------------------------------------------------------------------- #
# Fallbacks & Profiles
# --------------------------------------------------------------------------- #
# Software brightness LUT range
_BRIGHTNESS = Range(-50, 50, Source.APP_DEFINED, True, "software LUT in the app, not a hardware limit")


def _api_contract(ident: CameraIdentity) -> CameraLimits:
    """Conservative documented values: safe on any OAK, tight on newer sensors."""
    c = Source.API_CONTRACT
    return CameraLimits(
        identity=ident,
        gain=Range(100, 1600, c, False, "documented manual ISO range"),
        exposure_us=Range(1, 33_000, c, False, "documented manual exposure range"),
        focus=Range(0, 255, c, False, "8-bit lens position") if ident.has_autofocus else None,
        brightness=_BRIGHTNESS,
        contrast=Range(-10, 10, c, False, "CameraControl range; no readback to verify"),
    )


# (platform, sensor) -> measured overrides.
_P = Source.PROFILE
PROFILES: dict[tuple[str, str], dict[str, Range]] = {
    ("RVC4", "IMX586"): {
        "gain": Range(65, 16_585, _P, True, "floor and ceiling both clamped by the sensor"),
        "exposure_us": Range(86, 1_000_000, _P, False, "min measured; max is only the benchmark ceiling"),
        "focus": Range(0, 255, _P, True, "lens followed 0..255"),
        "contrast": Range(-10, 10, _P, True, "accepted; useful range ~ -10..+8"),
    },
    ("RVC2", "IMX378"): {
        "gain": Range(100, 6400, _P, True, "IMX378 hardware ISO limits"),
        "exposure_us": Range(100, 330_000, _P, False, "IMX378 exposure range"),
        "focus": Range(0, 255, _P, True, "VCM focus motor"),
        "contrast": Range(-10, 10, _P, True, "accepted range"),
    },
}


def _merged_fallback(ident: CameraIdentity) -> CameraLimits:
    lim = _api_contract(ident)
    for name, rng in PROFILES.get((ident.platform, ident.sensor), {}).items():
        if name == "focus" and not ident.has_autofocus:
            continue
        setattr(lim, name, rng)
    return lim


# --------------------------------------------------------------------------- #
# Probing (talks to hardware only through ProbeBackend)
# --------------------------------------------------------------------------- #
class ProbeBackend(Protocol):
    def apply_exposure_iso(self, exposure_us: int, iso: int) -> tuple[int, int]:
        """Set both; return (exposure_us, iso) as reported back by the sensor."""
        ...

    def apply_focus(self, position: int) -> Optional[int]:
        """Set lens position; return reported position, or None if rejected."""
        ...


def _close(a: float, b: float, rel: float = 0.01, abs_: float = 2.0) -> bool:
    """Readbacks can be off by one or two (e.g. 800 -> 799): rounding, not a clamp."""
    return abs(a - b) <= max(abs_, rel * abs(b))


def _bisect_edge(accepted: Callable[[int], bool], good: int, bad: int) -> int:
    while abs(bad - good) > 1:
        mid = (good + bad) // 2
        if accepted(mid):
            good = mid
        else:
            bad = mid
    return good


def _find_limit(apply: Callable[[float], Optional[float]], good: float, far: float):
    """Walk from a known-good value toward `far`; return (limit, verified)."""
    r = apply(far)
    rejected = r is None or (_close(r, good) and not _close(far, good))
    if rejected:
        ok = lambda v: (x := apply(v)) is not None and _close(x, v)
        return _bisect_edge(ok, int(good), int(far)), True
    if not _close(r, far):
        again = apply(r)
        return r, again is not None and _close(again, r)
    return far, False


def probe_limits(
    ident: CameraIdentity,
    backend: ProbeBackend,
    exposure_ceiling_us: Optional[int] = DEFAULT_EXPOSURE_CEILING_US
) -> CameraLimits:
    """Probe the running camera. Controls it cannot answer keep fallback values."""
    base = _merged_fallback(ident)
    P = Source.PROBED

    iso = lambda v: backend.apply_exposure_iso(8_000, int(v))[1]
    gain = base.gain
    if _close(iso(400), 400):
        lo, lo_ok = _find_limit(iso, 400, 1)
        hi, hi_ok = _find_limit(iso, 400, 1_000_000)
        gain = Range(lo, hi, P, lo_ok and hi_ok)

    exp = lambda v: backend.apply_exposure_iso(int(v), 400)[0]
    exposure = base.exposure_us
    if _close(exp(8_000), 8_000):
        lo, lo_ok = _find_limit(exp, 8_000, 1)
        if exposure_ceiling_us:
            hi, hi_ok = _find_limit(exp, 8_000, exposure_ceiling_us)
            exposure = Range(lo, hi, P, lo_ok and hi_ok, "" if hi_ok else "upper bound is the tested ceiling")
        else:
            exposure = Range(lo, base.exposure_us.max, P, False, "upper bound not probed")

    focus = None
    if ident.has_autofocus:
        focus = base.focus
        if backend.apply_focus(128) == 128:
            lo, _ = _find_limit(backend.apply_focus, 128, 0)
            hi, _ = _find_limit(backend.apply_focus, 128, 255)
            focus = Range(lo, hi, P, True, "8-bit lens position, readback tracked")

    return CameraLimits(ident, gain, exposure, focus, base.brightness, base.contrast)


# --------------------------------------------------------------------------- #
# Cache & Limits Service
# --------------------------------------------------------------------------- #
def _resolve_default_cache_path() -> Path:
    env_p = os.environ.get("CAMERA_LIMITS_CACHE")
    if env_p and env_p.strip():
        return Path(env_p.strip())
    try:
        from app.core.app_paths import APP_DIR
        return APP_DIR / "camera_limits.json"
    except Exception:
        return Path.home() / ".cache" / "camera_limits.json"


class CameraLimitsService:
    def __init__(self, cache_path: Optional[Path] = None):
        self._path = Path(cache_path) if cache_path else _resolve_default_cache_path()
        self._lock = threading.Lock()

    def get_cached(self, ident: CameraIdentity) -> Optional[CameraLimits]:
        with self._lock:
            entry = self._read().get("entries", {}).get(ident.key)
        try:
            lim = CameraLimits.from_dict(entry) if entry else None
        except (KeyError, TypeError, ValueError):
            return None
        if lim:
            lim.identity = ident
        return lim

    def get_limits(
        self,
        ident: CameraIdentity,
        backend: Optional[ProbeBackend] = None,
        force_probe: bool = False,
        exposure_ceiling_us: Optional[int] = DEFAULT_EXPOSURE_CEILING_US
    ) -> CameraLimits:
        """cache -> probe (if a backend is given) -> profile -> API contract."""
        if not force_probe:
            cached = self.get_cached(ident)
            if cached:
                return cached
        if backend is not None:
            try:
                limits = probe_limits(ident, backend, exposure_ceiling_us)
                self._put(ident.key, limits)
                return limits
            except Exception:
                logger.exception("Probe failed for %s; using fallback limits", ident.key)
        return _merged_fallback(ident)

    def _read(self) -> dict:
        try:
            if not self._path.exists():
                return {}
            data = json.loads(self._path.read_text(encoding="utf-8"))
            return data if data.get("schema") == SCHEMA_VERSION else {}
        except (OSError, ValueError):
            return {}

    def _put(self, key: str, limits: CameraLimits) -> None:
        with self._lock:
            data = self._read() or {"schema": SCHEMA_VERSION}
            data.setdefault("entries", {})[key] = limits.to_dict()
            self._path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=self._path.parent)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp, self._path)


_shared: Optional[CameraLimitsService] = None
_shared_lock = threading.Lock()


def get_limits_service() -> CameraLimitsService:
    global _shared
    with _shared_lock:
        if _shared is None:
            _shared = CameraLimitsService()
        return _shared


# --------------------------------------------------------------------------- #
# Live Probe Adapter for OakCameraService
# --------------------------------------------------------------------------- #
class ProbeError(RuntimeError):
    pass


class LiveServiceProbeBackend:
    def __init__(self, svc: Any, settle_frames: int = 6, stable_frames: int = 2, base_timeout_s: float = 3.0):
        self._svc = svc
        self._settle = settle_frames
        self._stable = stable_frames
        self._timeout = base_timeout_s

    def _send(self, ctrl) -> None:
        q = self._svc._control_queue
        if q is None:
            raise ProbeError("control queue is closed")
        q.send(ctrl)

    def _read_settled(self, keys: tuple[str, ...], timeout_s: float) -> tuple:
        svc, seen, last_seq = self._svc, [], self._svc._latest_bgr_seq
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            seq = svc._latest_bgr_seq
            if seq != last_seq:
                last_seq = seq
                t = svc._latest_telemetry
                seen.append(tuple(t.get(k) for k in keys))
                tail = seen[-self._stable:]
                if len(seen) >= self._settle and len(tail) == self._stable and len(set(tail)) == 1:
                    return tail[-1]
            time.sleep(0.005)
        raise ProbeError("camera did not settle (no frames or values kept changing)")

    def apply_exposure_iso(self, exposure_us: int, iso: int) -> tuple[int, int]:
        import depthai as dai
        ctrl = dai.CameraControl()
        ctrl.setManualExposure(int(exposure_us), int(iso))
        self._send(ctrl)
        exp, iso_ = self._read_settled(("exposure_us", "iso"), self._timeout + 10 * (exposure_us / 1e6))
        if exp is None or iso_ is None:
            raise ProbeError("telemetry missing exposure/iso")
        return int(exp), int(iso_)

    def apply_focus(self, position: int) -> Optional[int]:
        import depthai as dai
        try:
            ctrl = dai.CameraControl()
            ctrl.setAutoFocusMode(dai.CameraControl.AutoFocusMode.OFF)
            ctrl.setManualFocus(int(position))
        except (TypeError, ValueError, OverflowError, RuntimeError):
            return None
        self._send(ctrl)
        (lens,) = self._read_settled(("lens_position",), self._timeout)
        return None if lens is None else int(lens)


def identity_from_device(device, mxid: str = "", socket_name: str = "CAM_A") -> CameraIdentity:
    """Describe the camera from the connected device hardware."""
    platform, sensor, autofocus, modes = "UNKNOWN", "", True, ()
    if device is not None:
        try:
            p = device.getPlatform()
            platform = str(getattr(p, "name", p))
        except Exception:
            logger.debug("getPlatform failed", exc_info=True)
        try:
            for f in device.getConnectedCameraFeatures():
                if str(getattr(f.socket, "name", f.socket)) == socket_name:
                    sensor = str(getattr(f, "sensorName", "") or "")
                    autofocus = bool(getattr(f, "hasAutofocus", True))
                    modes = tuple(
                        StreamMode(c.width, c.height, getattr(c, "minFps", 0), getattr(c, "maxFps", 0))
                        for c in getattr(f, "configs", [])
                    )
                    break
        except Exception:
            logger.debug("getConnectedCameraFeatures failed", exc_info=True)

    if not sensor:
        sensor = f"unit:{mxid or 'unknown'}"
    return CameraIdentity(platform, sensor, socket_name, autofocus, modes)


def _wait_for_frames(svc, timeout_s: float = 5.0) -> bool:
    deadline, start_seq = time.monotonic() + timeout_s, svc._latest_bgr_seq
    while time.monotonic() < deadline:
        if svc._latest_bgr_seq != start_seq and svc._latest_telemetry.get("iso") is not None:
            return True
        time.sleep(0.02)
    return False


def discover_limits_for_service(
    svc,
    *,
    force: bool = False,
    limits_service: Optional[CameraLimitsService] = None,
    exposure_ceiling_us: Optional[int] = DEFAULT_EXPOSURE_CEILING_US
) -> CameraLimits:
    """Probes limits safely on pipeline startup before video streaming."""
    ls = limits_service or get_limits_service()
    ident = identity_from_device(svc.device, getattr(svc, "_connected_mxid", "") or "")
    if not force:
        cached = ls.get_cached(ident)
        if cached:
            logger.info("[LIMITS] Cache hit for %s", ident.key)
            return cached

    if svc._active_recording is not None or getattr(svc, "_is_streaming", False):
        logger.info("[LIMITS] Camera busy (recording/streaming); using fallback limits")
        return ls.get_limits(ident)

    if not svc._camera_calibration_lock.acquire(blocking=False):
        return ls.get_limits(ident)

    prev_calibrating, probed = svc._calibrating, False
    svc._calibrating = True
    try:
        if not _wait_for_frames(svc):
            logger.warning("[LIMITS] No frames arrived; using fallback limits")
            return ls.get_limits(ident)
        probed = True
        t0 = time.monotonic()
        limits = ls.get_limits(
            ident,
            LiveServiceProbeBackend(svc),
            force_probe=True,
            exposure_ceiling_us=exposure_ceiling_us
        )
        logger.info(
            "[LIMITS] Probed %s in %.1fs: gain=%s..%s exposure=%s..%s focus=%s",
            ident.key, time.monotonic() - t0, limits.gain.min, limits.gain.max,
            limits.exposure_us.min, limits.exposure_us.max,
            limits.focus and (limits.focus.min, limits.focus.max)
        )
        return limits
    finally:
        svc._calibrating = prev_calibrating
        svc._camera_calibration_lock.release()
        if probed:
            try:
                svc.update_controls(force_full=True)
            except Exception:
                logger.exception("[LIMITS] Failed to restore controls after probe")


# --------------------------------------------------------------------------- #
# Public API & Backward Compatible Helpers
# --------------------------------------------------------------------------- #
def safe_fps(fps: int | None, default: int = 30) -> int:
    """Validates that FPS is an integer between 5 and 60."""
    if isinstance(fps, int) and 5 <= fps <= 60:
        return fps
    logger.warning(f"[LIMITS] Invalid or out-of-range FPS '{fps}', falling back to {default}")
    return default


def get_supported_fps_options(resolution: str | None = None) -> list[int]:
    """Returns standard supported FPS options."""
    return list(STANDARD_FPS)


def compute_camera_control_limits(
    camera_id: int,
    configured_fps: int | None,
    resolution: str | None = "1920x1080",
    camera_instance: Any = None,
) -> dict[str, Any]:
    """
    Computes dynamic limits for camera controls based on discovered/cached hardware bounds and FPS.
    Returns complete dictionary matching the schema expected by the frontend.
    """
    fps = safe_fps(configured_fps, default=30)
    frame_period_us = 1_000_000 // fps
    recommended_max_exposure_us = 950_000 // fps
    default_exposure_us = min(8000, recommended_max_exposure_us)

    # 1. Resolve camera hardware identity
    ident: Optional[CameraIdentity] = None
    inst = camera_instance
    if inst is None:
        try:
            from app.services.oak_camera_service import oak_camera_service
            inst = oak_camera_service.get_instance(camera_id)
        except Exception:
            inst = None

    if inst and getattr(inst, "device", None) is not None:
        ident = identity_from_device(inst.device, getattr(inst, "_connected_mxid", "") or "")
    else:
        # Default fallback identity (Sony IMX586 on RVC4)
        ident = CameraIdentity("RVC4", "IMX586", "CAM_A", has_autofocus=True)

    # 2. Get hardware limits (cache -> profile -> api_contract)
    ls = get_limits_service()
    limits = ls.get_limits(ident)
    rec = limits.recommended(fps)

    # Keep inst cached limits updated
    if inst is not None:
        inst._discovered_limits = limits

    fps_options = limits.fps_options(1920, 1080) if resolution == "1920x1080" else list(STANDARD_FPS)

    # 3. Assemble response preserving exact keys expected by UI and tests
    return {
        "camera_id": camera_id,
        "resolution": resolution or "1920x1080",
        "fps": {
            "configured": fps,
            "min": 5,
            "max": 60,
            "options": fps_options,
        },
        "controls": {
            "gain": {
                "source": limits.gain.source.value,
                "scale": "log",
                "quantized": True,
                "verified": limits.gain.verified,
                "hardware_min": int(limits.gain.min),
                "hardware_max": int(limits.gain.max),
                "recommended_min": int(rec["gain"].min),
                "recommended_max": int(rec["gain"].max),
                "default": int(limits.gain.clamp(400)),
                "step": 1,
                "warnings": [
                    {
                        "op": "gt",
                        "value": int(rec["gain"].max),
                        "level": "warning",
                        "message": "High sensor noise and digital grain",
                    }
                ],
            },
            "exposure": {
                "source": limits.exposure_us.source.value,
                "scale": "log",
                "quantized": False,
                "verified": limits.exposure_us.verified,
                "unit": "us",
                "display_unit": "ms",
                "hardware_min": int(limits.exposure_us.min),
                "hardware_max": int(limits.exposure_us.max),
                "recommended_min": int(rec["exposure_us"].min),
                "recommended_max": recommended_max_exposure_us,
                "frame_period_us": frame_period_us,
                "default": default_exposure_us,
                "step": 100,
                "step_anchor": 100,
                "warnings": [
                    {
                        "op": "gt_frame_period",
                        "frame_period_us": frame_period_us,
                        "level": "warning",
                        "template": "Exposure exceeds frame period — stream will drop to ~{calc_fps} FPS",
                    },
                    {
                        "op": "between",
                        "gt": recommended_max_exposure_us,
                        "lte": frame_period_us,
                        "level": "info",
                        "message": "Near frame rate limit",
                    },
                ],
            },
            "focus": {
                "available": limits.focus is not None,
                "source": limits.focus.source.value if limits.focus else "none",
                "scale": "linear",
                "quantized": True,
                "verified": limits.focus.verified if limits.focus else False,
                "hardware_min": int(limits.focus.min) if limits.focus else 0,
                "hardware_max": int(limits.focus.max) if limits.focus else 0,
                "recommended_min": int(limits.focus.min) if limits.focus else 0,
                "recommended_max": int(limits.focus.max) if limits.focus else 0,
                "default": 128 if limits.focus else 0,
                "step": 1,
                "warnings": [],
            },
            "contrast": {
                "source": limits.contrast.source.value,
                "scale": "linear",
                "quantized": True,
                "verified": limits.contrast.verified,
                "hardware_min": int(limits.contrast.min),
                "hardware_max": int(limits.contrast.max),
                "recommended_min": int(rec["contrast"].min),
                "recommended_max": int(rec["contrast"].max),
                "default": 0,
                "step": 1,
                "warnings": [
                    {
                        "op": "lt",
                        "value": int(rec["contrast"].min),
                        "level": "info",
                        "message": "Low contrast creates a flat, washed-out image",
                    },
                    {
                        "op": "gt",
                        "value": int(rec["contrast"].max),
                        "level": "warning",
                        "message": "Extreme contrast risks clipping specular highlights",
                    },
                ],
            },
            "brightness": {
                "source": "software",
                "scale": "linear",
                "quantized": False,
                "verified": False,
                "min": int(limits.brightness.min),
                "max": int(limits.brightness.max),
                "recommended_min": int(rec["brightness"].min),
                "recommended_max": int(rec["brightness"].max),
                "default": 0,
                "step": 1,
                "warnings": [
                    {
                        "op": "abs_gt",
                        "value": int(rec["brightness"].max),
                        "level": "info",
                        "message": "Digital luma shift reduces dynamic range",
                    }
                ],
            },
        },
    }


def run_contrast_migration_v2(engine) -> None:
    """
    Safely migrates legacy contrast values (0..100 scale, neutral=50)
    to ISP hardware register range (-10..+10, neutral=0).
    Guarded by a schema_versions table so it is idempotent and safe across restarts.
    """
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "CREATE TABLE IF NOT EXISTS schema_versions (version INTEGER PRIMARY KEY);"
                )
            )
            current_v = conn.execute(
                text("SELECT MAX(version) FROM schema_versions;")
            ).scalar()

            if current_v is None or current_v < 2:
                logger.info("[MIGRATION] Running contrast schema migration v2 (legacy 0..100 -> -10..+10)")
                rows = conn.execute(text("SELECT id, contrast FROM cameras;")).fetchall()
                for row in rows:
                    cam_id = row[0]
                    c = row[1]
                    if c is not None:
                        new_c = max(-10, min(10, int(round((c - 50.0) / 5.0))))
                    else:
                        new_c = 0
                    conn.execute(
                        text("UPDATE cameras SET contrast = :nc WHERE id = :cid;"),
                        {"nc": new_c, "cid": cam_id},
                    )

                conn.execute(
                    text("INSERT INTO schema_versions (version) VALUES (2);")
                )
                logger.info("[MIGRATION] Contrast schema migration v2 applied successfully")
            else:
                logger.debug("[MIGRATION] Contrast schema v2 already applied")
    except Exception as e:
        logger.error(f"[MIGRATION] Contrast migration error: {e}", exc_info=True)
