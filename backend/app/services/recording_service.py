"""
Recording service — uses PyAV for per-frame timestamps.
Supports continuous clip chunking (e.g. 1 min, 3 min) with zero dropped frames,
automatic balance minutes capture on stop, crash/cable-disconnect resilience,
and unique session folder naming to guarantee zero overwrites.
"""

import av
from av.video.reformatter import VideoReformatter, ColorRange, Colorspace, ColorPrimaries, ColorTrc
import cv2
import numpy as np
import os
import queue
import threading
import time
import logging
import json
from fractions import Fraction
from datetime import datetime
from app.core.app_paths import get_desktop_dir
from app.services.camera_service import safe_camera_name

logger = logging.getLogger("recording-service")

# session_id -> RecordingSession
active_recordings: dict = {}

_NVENC_FUNCTIONAL: bool | None = None
_NVENC_LOCK = threading.Lock()

# When True, MKV (FFV1) bakes non-zero Software Brightness into the NV12 luma (Y)
# plane so recordings match live UI preview; brightness=0 remains 100% bit-exact sensor NV12.
LOSSLESS_BAKE_BRIGHTNESS = True
_LUMA_LUT_CACHE: dict[int, np.ndarray] = {}

# Precomputed 65536-entry LUT: maps 0..8000mm (0..8m) linearly to 0..255 uint8 for fast depth colormapping
_DEPTH_LUT = np.clip((np.arange(65536, dtype=np.float32) / 8000.0) * 255.0, 0.0, 255.0).astype(np.uint8)
_DEPTH_LUT[0] = 0


def _get_luma_lut(brightness: int) -> np.ndarray:
    b = max(-50, min(50, int(brightness)))
    if b not in _LUMA_LUT_CACHE:
        # Match cv2.LUT BGR brightness offset (b * 2.5 in 0..255) scaled to BT.601 Y span (219/255)
        offset = int(round(b * 2.5 * (219.0 / 255.0)))
        _LUMA_LUT_CACHE[b] = np.clip(np.arange(256, dtype=np.int16) + offset, 0, 255).astype(np.uint8)
    return _LUMA_LUT_CACHE[b]


def _is_nvenc_functional() -> bool:
    global _NVENC_FUNCTIONAL
    if _NVENC_FUNCTIONAL is not None:
        return _NVENC_FUNCTIONAL
    with _NVENC_LOCK:
        if _NVENC_FUNCTIONAL is not None:
            return _NVENC_FUNCTIONAL
        if "h264_nvenc" not in av.codec.codecs_available:
            _NVENC_FUNCTIONAL = False
            return False
        try:
            devnull = "nul" if os.name == "nt" else "/dev/null"
            c = av.open(devnull, mode="w", format="mp4")
            s = c.add_stream("h264_nvenc", rate=30)
            s.width = 64
            s.height = 64
            s.pix_fmt = "yuv420p"
            s.options = {"preset": "fast"}
            f = av.VideoFrame(64, 64, "yuv420p")
            s.encode(f)
            c.close()
            _NVENC_FUNCTIONAL = True
            logger.info("[RECORD] Hardware acceleration verified: h264_nvenc is functional")
            return True
        except Exception as e:
            logger.info(f"[RECORD] NVENC not functional on this system ({e}) — using optimized libx264")
            _NVENC_FUNCTIONAL = False
            return False


class RecordingSession:
    def __init__(
        self,
        session_id: str,
        width: int,
        height: int,
        fps: float = 30.0,
        root_path: str = None,
        recording_format: str = "MP4",
        camera_settings: dict | None = None,
        camera_id: int | None = None,
        camera_name: str | None = None,
        clip_duration_minutes: int | None = 1,
        record_depth: bool = False,
        depth_width: int | None = None,
        depth_height: int | None = None,
    ):
        now = datetime.now()
        if not root_path:
            root_path = _get_default_recording_path()

        safe_cam = safe_camera_name(camera_name or f"Camera_{camera_id or 1}")
        date_folder = now.strftime("%Y-%m-%d")
        parent_dir = os.path.join(root_path, safe_cam, date_folder)
        try:
            os.makedirs(parent_dir, exist_ok=True)
        except Exception as perm_err:
            ws_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            fallback_root = os.path.join(ws_root, "recordings")
            logger.warning(f"[RECORD] Cannot create {parent_dir}: {perm_err} — falling back to {fallback_root}")
            parent_dir = os.path.join(fallback_root, safe_cam, date_folder)
            os.makedirs(parent_dir, exist_ok=True)

        session_base = f"session_{now.strftime('%H-%M-%S')}"
        session_dir = os.path.join(parent_dir, session_base)
        counter = 1
        while os.path.exists(session_dir):
            session_dir = os.path.join(parent_dir, f"{session_base}_{counter}")
            counter += 1
        os.makedirs(session_dir, exist_ok=True)

        self.session_dir = session_dir
        self.session_id = session_id
        self.camera_id = camera_id or 1
        self.camera_name = camera_name or safe_cam
        self.clip_duration_minutes = max(1, int(clip_duration_minutes or 1))
        self.clip_duration_seconds = self.clip_duration_minutes * 60
        self.start_iso = now.isoformat()

        fmt = (recording_format or "MP4").upper()
        options = {}
        if fmt in ("AVI", "MJPEG"):
            fmt        = "AVI"
            codec_name = "mjpeg"
            pix_fmt    = "yuvj420p"
            ext        = ".avi"
            options    = {"qmin": "1", "qmax": "2"}
        elif fmt in ("FFV1", "MKV"):
            fmt        = "FFV1"
            codec_name = "ffv1"
            pix_fmt    = "yuv420p"
            ext        = ".mkv"
            options    = {"level": "3", "coder": "1", "context": "1", "slicecrc": "1", "slices": "16"}
        else:  # Default: MP4 (H.264)
            fmt        = "MP4"
            pix_fmt    = "yuv420p"
            ext        = ".mp4"
            if _is_nvenc_functional():
                codec_name = "h264_nvenc"
                options    = {"preset": "fast", "cq": "18"}
            else:
                codec_name = "libx264"
                options    = {"preset": "veryfast", "crf": "17"}

        self.fmt = fmt
        self.codec_name = codec_name
        self.pix_fmt = pix_fmt
        self.ext = ext
        self.codec_options = options
        self.width = width
        self.height = height
        self.is_raw_nv12 = (fmt == "FFV1")
        self._saw_nv12 = False

        # Depth recording configuration and state
        self.record_depth = bool(record_depth)
        self.depth_width = int(depth_width or width)
        self.depth_height = int(depth_height or height)
        self._saw_depth = False
        self._depth_lock = threading.Lock()
        self._latest_depth_raw: np.ndarray | None = None
        self._depth_raw_container = None
        self._depth_raw_stream = None
        self._depth_prev_container = None
        self._depth_prev_stream = None
        self._temp_depth_raw_path = None
        self._temp_depth_prev_path = None
        self._last_encoded_depth_raw_pts = -1
        self._last_mux_depth_raw_dts = -1
        self._last_encoded_depth_prev_pts = -1
        self._last_mux_depth_prev_dts = -1
        self._current_clip_depth_frames = 0
        self._total_depth_frames = 0

        # Per-session reformatter avoids cross-camera SwsContext races
        self._reformatter = VideoReformatter()

        # Preserve every accepted camera frame while the encoder drains it.
        # Preview uses a separate latest-frame path and never waits on this queue.
        self.frame_queue = queue.Queue()
        self.is_running  = False
        self._start_mono = time.monotonic()
        self._first_cam_ts_sec: float | None = None
        self._first_cam_offset_ms: int = 0
        self._total_frames = 0
        self._dropped_frames = 0
        self._camera_frames_missing = 0
        self._last_seq_num: int | None = None
        self._last_drop_log = 0.0
        self._last_backlog_log = 0.0
        self._last_frame_payload = None
        self._last_pts_ms = -1

        self.clips: list = []
        self._current_clip_index = 1
        self._current_clip_start_pts_ms = 0
        self._current_clip_frames = 0
        self._container = None
        self._stream = None
        self._last_encoded_pts = -1
        self._last_mux_dts = -1
        self._temp_clip_path = None

        self.thread = None
        self.camera_settings = camera_settings or {}
        self.settings_history = [{"elapsed_seconds": 0.0, "settings": self.camera_settings.copy()}]

        # Write initial session manifest
        self._write_session_json(status="recording")

        # Start worker thread
        self.is_running = True
        self.thread = threading.Thread(target=self._worker, daemon=True)
        self.thread.start()
        logger.info(
            f"[RECORD] Session started: {self.session_dir} | format={fmt} | "
            f"clip_split={self.clip_duration_minutes}m ({self.clip_duration_seconds}s) | {width}x{height}"
        )

    # ── Clip Container Lifecycle ──────────────────────────────────────────────

    def _open_clip(self, start_pts_ms: int):
        self._current_clip_start_pts_ms = start_pts_ms
        self._current_clip_frames = 0
        self._last_encoded_pts = -1
        self._last_mux_dts = -1

        self._temp_clip_path = os.path.join(
            self.session_dir, f"clip{self._current_clip_index:03d}_temp{self.ext}"
        )

        container_options = {}
        if self.fmt == "MP4":
            container_options = {"movflags": "frag_keyframe+empty_moov"}

        try:
            self._container = av.open(self._temp_clip_path, mode="w", options=container_options)
            self._stream = self._container.add_stream(self.codec_name, rate=1000)
            self._stream.width   = self.width
            self._stream.height  = self.height
            self._stream.pix_fmt = self.pix_fmt
            # Frame PTS values below are milliseconds. Keep the encoder and muxer
            # on that same clock so timestamp rescaling cannot produce damaged
            # GOPs or uneven frame timing across containers/codecs.
            self._stream.time_base = Fraction(1, 1000)
            self._stream.codec_context.time_base = Fraction(1, 1000)
            if self.codec_options:
                self._stream.options = self.codec_options
            if self.codec_name == "ffv1":
                try:
                    self._stream.codec_context.thread_type = "SLICE"
                    self._stream.codec_context.thread_count = min(16, os.cpu_count() or 4)
                except Exception:
                    pass

            # Tag H.264 VUI metadata for full-range BT.709 (matches OAK NV12/AVI/browser dynamic range)
            if self.fmt == "MP4":
                try:
                    self._stream.codec_context.colorspace = Colorspace.ITU709
                    self._stream.codec_context.color_primaries = ColorPrimaries.BT709
                    self._stream.codec_context.color_trc = ColorTrc.BT709
                    self._stream.codec_context.color_range = ColorRange.JPEG
                except Exception:
                    pass
            elif self.fmt == "FFV1":
                try:
                    self._stream.codec_context.colorspace = Colorspace.ITU601
                    self._stream.codec_context.color_primaries = ColorPrimaries.SMPTE170M
                    self._stream.codec_context.color_trc = ColorTrc.BT709
                    self._stream.codec_context.color_range = ColorRange.MPEG
                except Exception:
                    pass

            logger.info(f"[RECORD] Opened clip {self._current_clip_index} at {self._temp_clip_path}")
        except Exception as e:
            if self.fmt == "FFV1":
                logger.warning(f"[RECORD] Failed to open FFV1 clip with full options: {e}. Retrying minimal FFV1...")
                self.codec_options = {"level": "3"}
                try:
                    self._container = av.open(self._temp_clip_path, mode="w", options=container_options)
                    self._stream = self._container.add_stream("ffv1", rate=1000)
                    self._stream.width   = self.width
                    self._stream.height  = self.height
                    self._stream.pix_fmt = self.pix_fmt
                    self._stream.time_base = Fraction(1, 1000)
                    self._stream.codec_context.time_base = Fraction(1, 1000)
                    self._stream.options = self.codec_options
                    logger.info(f"[RECORD] Fallback succeeded: opened clip {self._current_clip_index} with minimal FFV1")
                except Exception as ex2:
                    logger.error(f"[RECORD] FFV1 clip container failed: {ex2}", exc_info=True)
                    self._container = None
                    self._stream = None
            elif self.fmt == "MP4" and self.codec_name != "libx264":
                logger.warning(f"[RECORD] Failed to open clip container with {self.codec_name}: {e}. Retrying with libx264...")
                self.codec_name = "libx264"
                self.codec_options = {"preset": "veryfast", "crf": "17"}
                try:
                    self._container = av.open(self._temp_clip_path, mode="w", options=container_options)
                    self._stream = self._container.add_stream(self.codec_name, rate=1000)
                    self._stream.width   = self.width
                    self._stream.height  = self.height
                    self._stream.pix_fmt = self.pix_fmt
                    self._stream.time_base = Fraction(1, 1000)
                    self._stream.codec_context.time_base = Fraction(1, 1000)
                    if self.codec_options:
                        self._stream.options = self.codec_options
                    try:
                        self._stream.codec_context.colorspace = Colorspace.ITU709
                        self._stream.codec_context.color_primaries = ColorPrimaries.BT709
                        self._stream.codec_context.color_trc = ColorTrc.BT709
                        self._stream.codec_context.color_range = ColorRange.JPEG
                    except Exception:
                        pass
                    logger.info(f"[RECORD] Fallback succeeded: opened clip {self._current_clip_index} with libx264")
                except Exception as ex2:
                    logger.error(f"[RECORD] Fallback clip container failed: {ex2}", exc_info=True)
                    self._container = None
                    self._stream = None
            else:
                logger.error(f"[RECORD] Failed to open clip container ({self.codec_name}): {e}", exc_info=True)
                self._container = None
                self._stream = None

        if self.record_depth or self._saw_depth:
            self._open_depth_containers(start_pts_ms)

    def _open_depth_containers(self, start_pts_ms: int):
        self._current_clip_depth_frames = 0
        self._last_encoded_depth_raw_pts = -1
        self._last_mux_depth_raw_dts = -1
        self._last_encoded_depth_prev_pts = -1
        self._last_mux_depth_prev_dts = -1

        # 1. 16-bit Lossless Raw Depth Container (FFV1 gray16le in .mkv — preserving exact mm Z-values)
        self._temp_depth_raw_path = os.path.join(
            self.session_dir, f"clip{self._current_clip_index:03d}_depth_raw_temp.mkv"
        )
        try:
            self._depth_raw_container = av.open(self._temp_depth_raw_path, mode="w")
            self._depth_raw_stream = self._depth_raw_container.add_stream("ffv1", rate=1000)
            self._depth_raw_stream.width = self.depth_width
            self._depth_raw_stream.height = self.depth_height
            self._depth_raw_stream.pix_fmt = "gray16le"
            self._depth_raw_stream.time_base = Fraction(1, 1000)
            self._depth_raw_stream.codec_context.time_base = Fraction(1, 1000)
            self._depth_raw_stream.options = {"level": "3", "coder": "1", "context": "1", "slicecrc": "1", "slices": "16"}
            try:
                self._depth_raw_stream.codec_context.thread_type = "SLICE"
                self._depth_raw_stream.codec_context.thread_count = min(16, os.cpu_count() or 4)
            except Exception:
                pass
            logger.info(f"[RECORD] Opened 16-bit lossless raw depth container at {self._temp_depth_raw_path}")
        except Exception as ex_dr:
            logger.warning(f"[RECORD] Failed to open depth raw container with slice options: {ex_dr}. Retrying basic FFV1...")
            try:
                self._depth_raw_container = av.open(self._temp_depth_raw_path, mode="w")
                self._depth_raw_stream = self._depth_raw_container.add_stream("ffv1", rate=1000)
                self._depth_raw_stream.width = self.depth_width
                self._depth_raw_stream.height = self.depth_height
                self._depth_raw_stream.pix_fmt = "gray16le"
                self._depth_raw_stream.time_base = Fraction(1, 1000)
                self._depth_raw_stream.codec_context.time_base = Fraction(1, 1000)
            except Exception as ex_dr2:
                logger.error(f"[RECORD] Failed to open depth raw container: {ex_dr2}", exc_info=True)
                self._depth_raw_container = None
                self._depth_raw_stream = None

        # 2. Visual Colormapped Depth Preview (matching chosen container format: MP4 / AVI / MKV)
        self._temp_depth_prev_path = os.path.join(
            self.session_dir, f"clip{self._current_clip_index:03d}_depth_preview_temp{self.ext}"
        )
        container_options = {"movflags": "frag_keyframe+empty_moov"} if self.fmt == "MP4" else {}
        try:
            self._depth_prev_container = av.open(self._temp_depth_prev_path, mode="w", options=container_options)
            self._depth_prev_stream = self._depth_prev_container.add_stream(self.codec_name, rate=1000)
            self._depth_prev_stream.width = self.depth_width
            self._depth_prev_stream.height = self.depth_height
            self._depth_prev_stream.pix_fmt = self.pix_fmt
            self._depth_prev_stream.time_base = Fraction(1, 1000)
            self._depth_prev_stream.codec_context.time_base = Fraction(1, 1000)
            if self.codec_options:
                self._depth_prev_stream.options = self.codec_options
            if self.fmt == "MP4":
                try:
                    self._depth_prev_stream.codec_context.colorspace = Colorspace.ITU709
                    self._depth_prev_stream.codec_context.color_primaries = ColorPrimaries.BT709
                    self._depth_prev_stream.codec_context.color_trc = ColorTrc.BT709
                    self._depth_prev_stream.codec_context.color_range = ColorRange.JPEG
                except Exception:
                    pass
            logger.info(f"[RECORD] Opened colormapped depth preview container at {self._temp_depth_prev_path}")
        except Exception as ex_dp:
            logger.warning(f"[RECORD] Failed to open depth preview container: {ex_dp}")
            self._depth_prev_container = None
            self._depth_prev_stream = None

    def _close_clip(self, end_pts_ms: int):
        if not self._container or not self._stream:
            return

        try:
            for pkt in self._stream.encode():
                if pkt.dts is not None:
                    if pkt.dts <= self._last_mux_dts:
                        pkt.dts = self._last_mux_dts + 1
                    self._last_mux_dts = pkt.dts
                if pkt.pts is not None and pkt.dts is not None and pkt.pts < pkt.dts:
                    pkt.pts = pkt.dts
                self._container.mux(pkt)
            self._container.close()
        except Exception as e:
            logger.warning(f"[RECORD] Error closing container for clip {self._current_clip_index}: {e}")
        finally:
            self._container = None
            self._stream = None

        duration_sec = max(0.1, (end_pts_ms - self._current_clip_start_pts_ms) / 1000.0)
        mins = int(duration_sec // 60)
        secs = int(duration_sec % 60)
        final_filename = f"clip{self._current_clip_index:03d}_{mins:02d}m{secs:02d}s{self.ext}"
        final_path = os.path.join(self.session_dir, final_filename)

        if os.path.exists(self._temp_clip_path):
            try:
                os.replace(self._temp_clip_path, final_path)
            except Exception:
                try:
                    import shutil
                    shutil.move(self._temp_clip_path, final_path)
                except Exception as err:
                    logger.error(f"[RECORD] Could not rename temp clip to final name: {err}")
                    final_path = self._temp_clip_path

        # Close & finalize 16-bit Lossless Raw Depth Container
        final_depth_raw_path = None
        if self._depth_raw_container and self._depth_raw_stream:
            try:
                for pkt in self._depth_raw_stream.encode():
                    if pkt.dts is not None:
                        if pkt.dts <= self._last_mux_depth_raw_dts:
                            pkt.dts = self._last_mux_depth_raw_dts + 1
                        self._last_mux_depth_raw_dts = pkt.dts
                    if pkt.pts is not None and pkt.dts is not None and pkt.pts < pkt.dts:
                        pkt.pts = pkt.dts
                    self._depth_raw_container.mux(pkt)
                self._depth_raw_container.close()
            except Exception as e_dr:
                logger.warning(f"[RECORD] Error closing depth raw container for clip {self._current_clip_index}: {e_dr}")
            finally:
                self._depth_raw_container = None
                self._depth_raw_stream = None

            if self._temp_depth_raw_path and os.path.exists(self._temp_depth_raw_path):
                final_depth_raw_filename = f"clip{self._current_clip_index:03d}_depth_raw_{mins:02d}m{secs:02d}s.mkv"
                final_depth_raw_path = os.path.join(self.session_dir, final_depth_raw_filename)
                try:
                    os.replace(self._temp_depth_raw_path, final_depth_raw_path)
                except Exception:
                    try:
                        import shutil
                        shutil.move(self._temp_depth_raw_path, final_depth_raw_path)
                    except Exception:
                        final_depth_raw_path = self._temp_depth_raw_path

        # Close & finalize Depth Preview Container
        final_depth_prev_path = None
        if self._depth_prev_container and self._depth_prev_stream:
            try:
                for pkt in self._depth_prev_stream.encode():
                    if pkt.dts is not None:
                        if pkt.dts <= self._last_mux_depth_prev_dts:
                            pkt.dts = self._last_mux_depth_prev_dts + 1
                        self._last_mux_depth_prev_dts = pkt.dts
                    if pkt.pts is not None and pkt.dts is not None and pkt.pts < pkt.dts:
                        pkt.pts = pkt.dts
                    self._depth_prev_container.mux(pkt)
                self._depth_prev_container.close()
            except Exception as e_dp:
                logger.warning(f"[RECORD] Error closing depth preview container for clip {self._current_clip_index}: {e_dp}")
            finally:
                self._depth_prev_container = None
                self._depth_prev_stream = None

            if self._temp_depth_prev_path and os.path.exists(self._temp_depth_prev_path):
                final_depth_prev_filename = f"clip{self._current_clip_index:03d}_depth_preview_{mins:02d}m{secs:02d}s{self.ext}"
                final_depth_prev_path = os.path.join(self.session_dir, final_depth_prev_filename)
                try:
                    os.replace(self._temp_depth_prev_path, final_depth_prev_path)
                except Exception:
                    try:
                        import shutil
                        shutil.move(self._temp_depth_prev_path, final_depth_prev_path)
                    except Exception:
                        final_depth_prev_path = self._temp_depth_prev_path

        clip_record = {
            "index": self._current_clip_index,
            "filename": os.path.basename(final_path),
            "path": final_path,
            "duration_seconds": round(duration_sec, 2),
            "frames": self._current_clip_frames,
        }
        if final_depth_raw_path:
            clip_record["depth_raw_filename"] = os.path.basename(final_depth_raw_path)
            clip_record["depth_raw_path"] = final_depth_raw_path
            clip_record["depth_raw_frames"] = self._current_clip_depth_frames
            clip_record["z_unit"] = "millimeter (uint16 raw 16-bit)"
        if final_depth_prev_path:
            clip_record["depth_preview_filename"] = os.path.basename(final_depth_prev_path)
            clip_record["depth_preview_path"] = final_depth_prev_path

        self.clips.append(clip_record)
        self._write_session_json(status="recording")
        logger.info(
            f"[RECORD] Finalized clip {self._current_clip_index}: {final_filename} "
            f"({round(duration_sec, 1)}s, {self._current_clip_frames} frames)"
        )

    def _write_session_json(self, status: str = "recording"):
        total_dur = time.monotonic() - self._start_mono
        has_depth = bool(self.record_depth or self._saw_depth or self._total_depth_frames > 0)
        manifest = {
            "session_id": self.session_id,
            "camera_id": self.camera_id,
            "camera_name": self.camera_name,
            "folder": self.session_dir,
            "format": self.fmt,
            "resolution": f"{self.width}x{self.height}",
            "clip_duration_minutes": self.clip_duration_minutes,
            "start_time": self.start_iso,
            "end_time": datetime.now().isoformat() if status != "recording" else None,
            "status": status,
            "total_duration_seconds": round(total_dur, 2),
            "total_frames": self._total_frames,
            "dropped_frames": self._dropped_frames,
            "encoder_backlog_drops": self._dropped_frames,
            "camera_frames_missing": self._camera_frames_missing,
            "lossless_mode": "raw_nv12" if (self.is_raw_nv12 and self._saw_nv12) else ("bgr_lossless" if self.fmt == "FFV1" else "standard"),
            "has_depth": has_depth,
            "depth_resolution": f"{self.depth_width}x{self.depth_height}" if has_depth else None,
            "depth_format": f"16-bit Lossless FFV1 (gray16le) + Turbo Preview ({self.fmt})" if has_depth else None,
            "depth_z_unit": "millimeter (uint16 raw 16-bit)" if has_depth else None,
            "total_depth_frames": self._total_depth_frames if has_depth else 0,
            "settings_history": list(self.settings_history),
            "clips": [
                {
                    "index": c["index"],
                    "filename": c["filename"],
                    "duration_seconds": c["duration_seconds"],
                    "frames": c["frames"],
                    **({"depth_raw_filename": c["depth_raw_filename"]} if "depth_raw_filename" in c else {}),
                    **({"depth_raw_frames": c.get("depth_raw_frames", c["frames"])} if "depth_raw_filename" in c else {}),
                    **({"depth_preview_filename": c["depth_preview_filename"]} if "depth_preview_filename" in c else {}),
                }
                for c in self.clips
            ],
        }
        json_path = os.path.join(self.session_dir, "session.json")
        try:
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(manifest, f, indent=2)
        except Exception as e:
            logger.warning(f"[RECORD] Error updating session.json: {e}")

    # ── Worker Thread (Continuous chunking with balance retention) ────────────

    def _final_clip_end_pts(self) -> int:
        if self._current_clip_frames > 0 and self._last_pts_ms >= self._current_clip_start_pts_ms:
            return self._last_pts_ms
        return int((time.monotonic() - self._start_mono) * 1000)

    def _build_video_frame(self, payload) -> av.VideoFrame:
        if isinstance(payload, tuple) and len(payload) == 4 and payload[0] == "nv12":
            _, y_plane, uv_plane, b_val = payload
            if LOSSLESS_BAKE_BRIGHTNESS and b_val != 0:
                y_plane = cv2.LUT(y_plane, _get_luma_lut(b_val))
            frame = av.VideoFrame(self.width, self.height, "yuv420p")
            frame.planes[0].update(np.ascontiguousarray(y_plane).tobytes())
            frame.planes[1].update(np.ascontiguousarray(uv_plane[:, 0::2]).tobytes())
            frame.planes[2].update(np.ascontiguousarray(uv_plane[:, 1::2]).tobytes())
            frame.colorspace = Colorspace.ITU601
            frame.color_range = ColorRange.MPEG
            return frame

        frame = av.VideoFrame.from_ndarray(payload, format="bgr24")
        if self.fmt == "MP4":
            # Full-range BT.709 conversion (matches AVI and browser dynamic range without lifted shadows)
            frame = self._reformatter.reformat(
                frame,
                format=self._stream.pix_fmt,
                src_color_range="JPEG",
                dst_color_range="JPEG",
                src_colorspace="ITU709",
                dst_colorspace="ITU709",
            )
            frame.color_range = ColorRange.JPEG
        elif frame.format.name != self._stream.pix_fmt:
            frame = self._reformatter.reformat(frame, format=self._stream.pix_fmt)
        return frame

    def _worker(self):
        clip_duration_ms = int(self.clip_duration_seconds * 1000)
        self._open_clip(start_pts_ms=0)

        try:
            while self.is_running or not self.frame_queue.empty():
                try:
                    payload, pts_ms = self.frame_queue.get(timeout=0.5)
                except queue.Empty:
                    continue

                try:
                    # Check if interval reached -> rotate to next clip smoothly
                    if (pts_ms - self._current_clip_start_pts_ms) >= clip_duration_ms:
                        self._close_clip(pts_ms)
                        self._current_clip_index += 1
                        self._open_clip(start_pts_ms=pts_ms)

                    if not self._container or not self._stream:
                        continue

                    # Frame PTS relative to the start of this specific clip (each clip starts from 0)
                    rel_pts = pts_ms - self._current_clip_start_pts_ms
                    if rel_pts <= self._last_encoded_pts:
                        rel_pts = self._last_encoded_pts + 1
                    self._last_encoded_pts = rel_pts

                    color_payload = None
                    depth_uint16 = None
                    if isinstance(payload, tuple) and len(payload) == 3 and payload[0] == "dual":
                        color_payload = payload[1]
                        depth_uint16 = payload[2]
                    elif isinstance(payload, tuple) and len(payload) == 2 and payload[0] == "depth_only":
                        depth_uint16 = payload[1]
                    else:
                        color_payload = payload

                    # 1. Encode normal color video frame
                    if color_payload is not None and self._container and self._stream:
                        frame = self._build_video_frame(color_payload)
                        frame.pts = rel_pts
                        frame.time_base = Fraction(1, 1000)

                        for pkt in self._stream.encode(frame):
                            if pkt.dts is not None:
                                if pkt.dts <= self._last_mux_dts:
                                    pkt.dts = self._last_mux_dts + 1
                                self._last_mux_dts = pkt.dts
                            if pkt.pts is not None and pkt.dts is not None and pkt.pts < pkt.dts:
                                pkt.pts = pkt.dts
                            self._container.mux(pkt)

                        self._total_frames += 1
                        self._current_clip_frames += 1

                    # 2. Encode depth video frames (Lossless 16-bit raw + Turbo colormap preview)
                    if depth_uint16 is not None:
                        if not self._depth_raw_container and (self.record_depth or self._saw_depth):
                            self._open_depth_containers(self._current_clip_start_pts_ms)

                        # 2a. Lossless Raw Depth Frame (FFV1 gray16le — bit-exact millimeters Z preserved)
                        if self._depth_raw_container and self._depth_raw_stream is not None:
                            rel_pts_raw = rel_pts
                            if rel_pts_raw <= self._last_encoded_depth_raw_pts:
                                rel_pts_raw = self._last_encoded_depth_raw_pts + 1
                            self._last_encoded_depth_raw_pts = rel_pts_raw

                            f_raw = av.VideoFrame.from_ndarray(depth_uint16, format="gray16le")
                            f_raw.pts = rel_pts_raw
                            f_raw.time_base = Fraction(1, 1000)
                            for pkt in self._depth_raw_stream.encode(f_raw):
                                if pkt.dts is not None:
                                    if pkt.dts <= self._last_mux_depth_raw_dts:
                                        pkt.dts = self._last_mux_depth_raw_dts + 1
                                    self._last_mux_depth_raw_dts = pkt.dts
                                if pkt.pts is not None and pkt.dts is not None and pkt.pts < pkt.dts:
                                    pkt.pts = pkt.dts
                                self._depth_raw_container.mux(pkt)

                        # 2b. Visual Turbo Colormap Depth Preview (matching normal video format)
                        if self._depth_prev_container and self._depth_prev_stream is not None:
                            rel_pts_prev = rel_pts
                            if rel_pts_prev <= self._last_encoded_depth_prev_pts:
                                rel_pts_prev = self._last_encoded_depth_prev_pts + 1
                            self._last_encoded_depth_prev_pts = rel_pts_prev

                            depth_scaled = cv2.LUT(depth_uint16, _DEPTH_LUT)
                            depth_color = cv2.applyColorMap(depth_scaled, cv2.COLORMAP_TURBO)
                            depth_color[depth_uint16 == 0] = [0, 0, 0]

                            f_prev = av.VideoFrame.from_ndarray(depth_color, format="bgr24")
                            if self.fmt == "MP4":
                                f_prev = self._reformatter.reformat(
                                    f_prev,
                                    format=self._depth_prev_stream.pix_fmt,
                                    src_color_range="JPEG",
                                    dst_color_range="JPEG",
                                    src_colorspace="ITU709",
                                    dst_colorspace="ITU709",
                                )
                                f_prev.color_range = ColorRange.JPEG
                            elif f_prev.format.name != self._depth_prev_stream.pix_fmt:
                                f_prev = self._reformatter.reformat(f_prev, format=self._depth_prev_stream.pix_fmt)

                            f_prev.pts = rel_pts_prev
                            f_prev.time_base = Fraction(1, 1000)
                            for pkt in self._depth_prev_stream.encode(f_prev):
                                if pkt.dts is not None:
                                    if pkt.dts <= self._last_mux_depth_prev_dts:
                                        pkt.dts = self._last_mux_depth_prev_dts + 1
                                    self._last_mux_depth_prev_dts = pkt.dts
                                if pkt.pts is not None and pkt.dts is not None and pkt.pts < pkt.dts:
                                    pkt.pts = pkt.dts
                                self._depth_prev_container.mux(pkt)

                        self._current_clip_depth_frames += 1
                        self._total_depth_frames += 1

                except Exception as e:
                    logger.warning(f"[RECORD] Frame encode warning: {e}")
                    time.sleep(0.01)

        except Exception as e:
            logger.error(f"[RECORD] Worker fatal exception: {e}", exc_info=True)
            if self._container:
                self._close_clip(self._final_clip_end_pts())
                self._write_session_json(status="interrupted_error")
        finally:
            if self._container:
                self._close_clip(self._final_clip_end_pts())
            self._write_session_json(status="completed")
            logger.info(f"[RECORD] Finished session — {len(self.clips)} clips written to {self.session_dir}")

    # ── Public API ────────────────────────────────────────────────────────────

    def _enqueue_payload(self, payload, pts_ms: int) -> None:
        self._last_frame_payload = payload
        self.frame_queue.put_nowait((payload, pts_ms))
        backlog = self.frame_queue.qsize()
        now = time.monotonic()
        if backlog >= 300 and now - self._last_backlog_log >= 2.0:
            self._last_backlog_log = now
            logger.warning(
                f"[RECORD] Encoder backlog is {backlog} frames; preserving all frames while the encoder catches up"
            )

    def add_depth_frame(
        self,
        depth_raw_16: np.ndarray,
        cam_ts_sec: float | None = None,
        seq_num: int | None = None,
    ) -> None:
        """Add raw 16-bit millimeter depth frame (uint16, 0..65535mm)."""
        if not self.is_running or depth_raw_16 is None:
            return
        if depth_raw_16.dtype != np.uint16:
            depth_raw_16 = np.ascontiguousarray(depth_raw_16, dtype=np.uint16)
        else:
            depth_raw_16 = np.ascontiguousarray(depth_raw_16)

        with self._depth_lock:
            self._saw_depth = True
            self.record_depth = True
            self.depth_height, self.depth_width = depth_raw_16.shape[:2]
            self._latest_depth_raw = depth_raw_16.copy()

    def add_dual_frame(
        self,
        color_frame,
        depth_raw_16: np.ndarray,
        cam_ts_sec: float | None = None,
        seq_num: int | None = None,
    ) -> None:
        """Add synchronized color + raw 16-bit depth frame pair directly."""
        if not self.is_running:
            return
        if depth_raw_16 is not None:
            self.add_depth_frame(depth_raw_16, cam_ts_sec=cam_ts_sec, seq_num=seq_num)

        if color_frame is not None:
            self.add_frame(color_frame)

    def add_nv12_frame(
        self,
        y_plane: np.ndarray,
        uv_plane: np.ndarray,
        cam_ts_sec: float | None = None,
        seq_num: int | None = None,
        brightness: int = 0,
    ) -> None:
        """Add raw sensor NV12 Y/UV planes directly for bit-exact FFV1 recording."""
        if not self.is_running:
            return
        self._saw_nv12 = True

        if seq_num is not None:
            if self._last_seq_num is not None and seq_num > self._last_seq_num + 1:
                self._camera_frames_missing += (seq_num - self._last_seq_num - 1)
            self._last_seq_num = seq_num

        if cam_ts_sec is not None:
            if self._first_cam_ts_sec is None:
                self._first_cam_ts_sec = cam_ts_sec
                self._first_cam_offset_ms = max(0, int((time.monotonic() - self._start_mono) * 1000))
            pts_ms = self._first_cam_offset_ms + int((cam_ts_sec - self._first_cam_ts_sec) * 1000)
        else:
            pts_ms = int((time.monotonic() - self._start_mono) * 1000)

        if pts_ms <= self._last_pts_ms:
            pts_ms = self._last_pts_ms + 1
        self._last_pts_ms = pts_ms

        color_payload = ("nv12", y_plane, uv_plane, int(brightness or 0))
        with self._depth_lock:
            d_frame = self._latest_depth_raw
            if d_frame is not None and (self.record_depth or self._saw_depth):
                payload = ("dual", color_payload, d_frame)
            else:
                payload = color_payload

        self._enqueue_payload(payload, pts_ms)

    def add_frame(self, bgr, cam_ts_sec: float | None = None, seq_num: int | None = None, copy_frame: bool = True):
        """Add uncompressed BGR frame directly to the recording queue."""
        if not self.is_running:
            return
        if self.is_raw_nv12 and self._saw_nv12:
            return

        if seq_num is not None:
            if self._last_seq_num is not None and seq_num > self._last_seq_num + 1:
                self._camera_frames_missing += seq_num - self._last_seq_num - 1
            self._last_seq_num = seq_num

        if cam_ts_sec is not None:
            if self._first_cam_ts_sec is None:
                self._first_cam_ts_sec = cam_ts_sec
                self._first_cam_offset_ms = max(0, int((time.monotonic() - self._start_mono) * 1000))
            pts_ms = self._first_cam_offset_ms + int((cam_ts_sec - self._first_cam_ts_sec) * 1000)
        else:
            pts_ms = int((time.monotonic() - self._start_mono) * 1000)
        if pts_ms <= self._last_pts_ms:
            pts_ms = self._last_pts_ms + 1
        self._last_pts_ms = pts_ms

        # The camera packet worker may transfer its freshly allocated image
        # without another full-frame copy; other callers retain safe copy behavior.
        color_payload = np.ascontiguousarray(bgr)
        if copy_frame:
            color_payload = color_payload.copy()
        with self._depth_lock:
            d_frame = self._latest_depth_raw
            if d_frame is not None and (self.record_depth or self._saw_depth):
                payload = ("dual", color_payload, d_frame)
            else:
                payload = color_payload

        self._enqueue_payload(payload, pts_ms)

    def add_jpeg_frame(self, jpeg_bytes: bytes) -> None:
        """Compatibility shim — decodes JPEG if a caller passes JPEG bytes."""
        if not self.is_running:
            return
        try:
            arr = np.frombuffer(jpeg_bytes, dtype=np.uint8)
            bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if bgr is not None:
                self.add_frame(bgr)
        except Exception:
            pass

    def add_settings_event(self, settings: dict) -> None:
        elapsed = round(time.monotonic() - self._start_mono, 3)
        event = {"elapsed_seconds": elapsed, "settings": settings.copy()}
        self.camera_settings = settings.copy()
        if self.settings_history and self.settings_history[-1]["settings"] == settings:
            return
        self.settings_history.append(event)

    def stop(self) -> dict:
        if self._last_frame_payload is not None:
            pad_pts_ms = int((time.monotonic() - self._start_mono) * 1000)
            if pad_pts_ms <= self._last_pts_ms:
                pad_pts_ms = self._last_pts_ms + 1
            gap_ms = pad_pts_ms - self._last_pts_ms
            self._last_pts_ms = pad_pts_ms
            logger.info(f"[RECORD] Padding final clip by {gap_ms} ms")
            try:
                self.frame_queue.put_nowait((self._last_frame_payload, pad_pts_ms))
            except queue.Full:
                pass

        logger.info(f"[RECORD] Stopping session — {self.frame_queue.qsize()} frames in queue")
        self.is_running = False
        if self.thread is not None:
            self.thread.join(timeout=30.0)
            if self.thread.is_alive():
                logger.warning("[RECORD] Worker thread did not terminate within 30s")

        duration = time.monotonic() - self._start_mono
        first_clip_path = self.clips[0]["path"] if self.clips else os.path.join(self.session_dir, "clip001" + self.ext)
        last_filename = self.clips[-1]["filename"] if self.clips else "session.json"

        return {
            "recording_path": first_clip_path,
            "session_dir": self.session_dir,
            "filename": last_filename,
            "duration": round(duration, 2),
            "frames_written": self._total_frames,
            "depth_frames_written": self._total_depth_frames,
            "has_depth": bool(self._total_depth_frames > 0 or self._saw_depth),
            "dropped_frames": self._dropped_frames,
            "camera_frames_missing": self._camera_frames_missing,
            "format": self.fmt,
            "width": self.width,
            "height": self.height,
            "clips": self.clips,
            "camera_id": self.camera_id,
            "camera_name": self.camera_name,
        }


def _get_default_recording_path() -> str:
    from app.core.app_paths import get_configured_storage_dir
    return str(get_configured_storage_dir() / "recordings")


def _resolve_recording_path(root_path: str = None) -> str:
    if root_path and root_path.strip():
        return root_path.strip()
    return _get_default_recording_path()


def start_recording(
    session_id: str,
    width: int,
    height: int,
    fps: float = 30.0,
    root_path: str = None,
    recording_format: str = "MP4",
    camera_settings: dict | None = None,
    camera_id: int | None = None,
    camera_name: str | None = None,
    clip_duration_minutes: int | None = 1,
    record_depth: bool = False,
    depth_width: int | None = None,
    depth_height: int | None = None,
) -> str:
    logger.info(f"[RECORD] Creating session: {session_id} | format={recording_format} | record_depth={record_depth} | camera={camera_name} (ID: {camera_id})")
    if session_id in active_recordings:
        logger.warning("[RECORD] Session already exists — returning existing session directory")
        return active_recordings[session_id].session_dir

    root_path = _resolve_recording_path(root_path)
    session = RecordingSession(
        session_id=session_id,
        width=width,
        height=height,
        fps=fps,
        root_path=root_path,
        recording_format=recording_format,
        camera_settings=camera_settings,
        camera_id=camera_id,
        camera_name=camera_name,
        clip_duration_minutes=clip_duration_minutes,
        record_depth=record_depth,
        depth_width=depth_width,
        depth_height=depth_height,
    )

    if not session.is_running:
        raise RuntimeError(
            f"Recording session failed to start for session {session_id}."
        )

    active_recordings[session_id] = session
    return session.session_dir


def write_frame(session_id: str, frame) -> None:
    session = active_recordings.get(session_id)
    if session:
        session.add_frame(frame)


def write_depth_frame(session_id: str, depth_raw_16: np.ndarray) -> None:
    session = active_recordings.get(session_id)
    if session:
        session.add_depth_frame(depth_raw_16)


def stop_recording(session_id: str) -> dict:
    session = active_recordings.pop(session_id, None)
    if not session:
        logger.warning(f"[RECORD] No active session: {session_id}")
        return {}
    return session.stop()
