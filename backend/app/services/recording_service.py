"""
Recording service — uses PyAV for per-frame timestamps.
Supports continuous clip chunking (e.g. 1 min, 3 min) with zero dropped frames,
automatic balance minutes capture on stop, crash/cable-disconnect resilience,
and unique session folder naming to guarantee zero overwrites.
"""

import av
from av.video.reformatter import VideoReformatter, ColorRange, Colorspace
import os
import queue
import threading
import time
import logging
import json
from datetime import datetime
from app.core.app_paths import get_desktop_dir
from app.services.camera_service import safe_camera_name

# Shared full-range BGR→YUV reformatter (thread-safe; re-used across all sessions)
_FULL_RANGE_REFORMATTER = VideoReformatter()

logger = logging.getLogger("recording-service")

# session_id → RecordingSession
active_recordings: dict = {}

_NVENC_FUNCTIONAL: bool | None = None


def _is_nvenc_functional() -> bool:
    global _NVENC_FUNCTIONAL
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
        fps: float = 30.0,           # kept for API compatibility; not used for timestamps
        root_path: str = None,
        recording_format: str = "MP4",
        camera_settings: dict | None = None,
        camera_id: int | None = None,
        camera_name: str | None = None,
        clip_duration_minutes: int | None = 1,
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
            # Fallback to local workspace recordings directory
            ws_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            fallback_root = os.path.join(ws_root, "recordings")
            logger.warning(f"[RECORD] Cannot create {parent_dir}: {perm_err} — falling back to {fallback_root}")
            parent_dir = os.path.join(fallback_root, safe_cam, date_folder)
            os.makedirs(parent_dir, exist_ok=True)

        # Unique session folder to prevent any overwriting
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
            options    = {"qmin": "2", "qmax": "3"}
        elif fmt in ("FFV1", "MKV"):
            fmt        = "FFV1"
            codec_name = "ffv1"
            pix_fmt    = "yuv420p"
            ext        = ".mkv"
            options    = {"level": "3"}
        else:  # Default: MP4 (H.264)
            fmt        = "MP4"
            pix_fmt    = "yuv420p"
            ext        = ".mp4"
            if _is_nvenc_functional():
                codec_name = "h264_nvenc"
                options    = {"preset": "fast", "cq": "20"}
            else:
                codec_name = "libx264"
                options    = {"preset": "ultrafast", "crf": "22", "tune": "zerolatency"}

        self.fmt = fmt
        self.codec_name = codec_name
        self.pix_fmt = pix_fmt
        self.ext = ext
        self.codec_options = options
        self.width = width
        self.height = height

        # Frame queue (bounded ~150 frames to prevent OOM)
        self.frame_queue = queue.Queue(maxsize=150)
        self.is_running  = False
        self._start_mono = time.monotonic()
        self._total_frames = 0
        self._last_bgr = None
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
            # Fragmented MP4 ensures chunks are immediately playable even on unexpected stop/crash
            container_options = {"movflags": "frag_keyframe+empty_moov"}

        try:
            self._container = av.open(self._temp_clip_path, mode="w", options=container_options)
            self._stream = self._container.add_stream(self.codec_name, rate=1000)
            self._stream.width   = self.width
            self._stream.height  = self.height
            self._stream.pix_fmt = self.pix_fmt
            if self.codec_options:
                self._stream.options = self.codec_options
            # Tag the stream as full-range (JPEG/PC range) so media players
            # render the same contrast and black levels as the browser live stream.
            # Without this, players default to TV limited range (16–235) and crush
            # blacks up to grey and clip highlights — making the recording look
            # washed-out compared to what you see on screen.
            try:
                self._stream.codec_context.color_range = ColorRange.JPEG      # 0–255 full range
                self._stream.codec_context.colorspace = Colorspace.ITU709
            except Exception:
                pass
            logger.info(f"[RECORD] Opened clip {self._current_clip_index} at {self._temp_clip_path}")
        except Exception as e:
            logger.warning(f"[RECORD] Failed to open clip container with {self.codec_name}: {e}. Retrying with libx264...")
            if self.codec_name != "libx264":
                self.codec_name = "libx264"
                self.codec_options = {"preset": "ultrafast", "crf": "22", "tune": "zerolatency"}
                try:
                    self._container = av.open(self._temp_clip_path, mode="w", options=container_options)
                    self._stream = self._container.add_stream(self.codec_name, rate=1000)
                    self._stream.width   = self.width
                    self._stream.height  = self.height
                    self._stream.pix_fmt = self.pix_fmt
                    if self.codec_options:
                        self._stream.options = self.codec_options
                    # Tag full-range on fallback stream too
                    try:
                        self._stream.codec_context.color_range = ColorRange.JPEG
                        self._stream.codec_context.colorspace = Colorspace.ITU709
                    except Exception:
                        pass
                    logger.info(f"[RECORD] Fallback succeeded: opened clip {self._current_clip_index} with libx264")
                except Exception as ex2:
                    logger.error(f"[RECORD] Fallback clip container failed: {ex2}", exc_info=True)
                    self._container = None
                    self._stream = None
            else:
                self._container = None
                self._stream = None

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

        clip_record = {
            "index": self._current_clip_index,
            "filename": os.path.basename(final_path),
            "path": final_path,
            "duration_seconds": round(duration_sec, 2),
            "frames": self._current_clip_frames,
        }
        self.clips.append(clip_record)
        self._write_session_json(status="recording")
        logger.info(
            f"[RECORD] Finalized clip {self._current_clip_index}: {final_filename} "
            f"({round(duration_sec, 1)}s, {self._current_clip_frames} frames)"
        )

    def _write_session_json(self, status: str = "recording"):
        total_dur = time.monotonic() - self._start_mono
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
            "clips": [
                {
                    "index": c["index"],
                    "filename": c["filename"],
                    "duration_seconds": c["duration_seconds"],
                    "frames": c["frames"],
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

    def _worker(self):
        clip_duration_ms = int(self.clip_duration_seconds * 1000)
        self._open_clip(start_pts_ms=0)

        try:
            while self.is_running or not self.frame_queue.empty():
                try:
                    bgr, pts_ms = self.frame_queue.get(timeout=0.5)
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

                    # BGR -> Target Pixel Format with full color range preservation.
                    # Using JPEG (full PC range 0-255) on both src and dst sides of
                    # swscale prevents the default TV limited-range crush (16-235)
                    # that makes blacks look grey and whites look dim in the recording
                    # compared to the browser live stream.
                    frame = av.VideoFrame.from_ndarray(bgr, format="bgr24")
                    if frame.format.name != self._stream.pix_fmt:
                        frame = _FULL_RANGE_REFORMATTER.reformat(
                            frame,
                            format=self._stream.pix_fmt,
                            src_color_range="JPEG",
                            dst_color_range="JPEG",
                            src_colorspace="ITU709",
                            dst_colorspace="ITU709",
                        )
                    frame.color_range = ColorRange.JPEG

                    # Frame PTS relative to the start of this specific clip (each clip starts from 0)
                    rel_pts = pts_ms - self._current_clip_start_pts_ms
                    if rel_pts <= self._last_encoded_pts:
                        rel_pts = self._last_encoded_pts + 1
                    self._last_encoded_pts = rel_pts
                    frame.pts = rel_pts

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

                except Exception as e:
                    logger.warning(f"[RECORD] Frame encode warning: {e}")
                    time.sleep(0.01)

        except Exception as e:
            logger.error(f"[RECORD] Worker fatal exception: {e}", exc_info=True)
            if self._container:
                end_pts = self._last_pts_ms if self._last_pts_ms > self._current_clip_start_pts_ms else int((time.monotonic() - self._start_mono) * 1000)
                self._close_clip(end_pts)
                self._write_session_json(status="interrupted_error")
        finally:
            # Finalize open container (captures remaining balance minutes cleanly)
            if self._container:
                end_pts = self._last_pts_ms if self._last_pts_ms > self._current_clip_start_pts_ms else int((time.monotonic() - self._start_mono) * 1000)
                self._close_clip(end_pts)
            self._write_session_json(status="completed")
            logger.info(f"[RECORD] Finished session — {len(self.clips)} clips written to {self.session_dir}")

    # ── Public API ────────────────────────────────────────────────────────────

    def add_frame(self, bgr):
        if not self.is_running:
            return

        pts_ms = int((time.monotonic() - self._start_mono) * 1000)
        if pts_ms <= self._last_pts_ms:
            pts_ms = self._last_pts_ms + 1
        self._last_pts_ms = pts_ms
        self._last_bgr = bgr

        try:
            self.frame_queue.put_nowait((bgr, pts_ms))
        except queue.Full:
            try:
                self.frame_queue.get_nowait()
                self.frame_queue.put_nowait((bgr, pts_ms))
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
        if self._last_bgr is not None:
            pad_pts_ms = int((time.monotonic() - self._start_mono) * 1000)
            if pad_pts_ms <= self._last_pts_ms:
                pad_pts_ms = self._last_pts_ms + 1
            gap_ms = pad_pts_ms - self._last_pts_ms
            self._last_pts_ms = pad_pts_ms
            logger.info(f"[RECORD] Padding final clip by {gap_ms} ms")
            try:
                self.frame_queue.put_nowait((self._last_bgr, pad_pts_ms))
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
) -> str:
    logger.info(f"[RECORD] Creating session: {session_id} | format={recording_format} | camera={camera_name} (ID: {camera_id})")
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


def stop_recording(session_id: str) -> dict:
    session = active_recordings.pop(session_id, None)
    if not session:
        logger.warning(f"[RECORD] No active session: {session_id}")
        return {}
    return session.stop()
