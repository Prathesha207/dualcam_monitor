# backend/app/services/camera_limits_service.py
"""
Three-Zone Camera Controls & Dynamic Limits Engine.
Publishes physical hardware boundaries, policy/recommended ranges,
and structured warning thresholds based on configured camera FPS.
"""

import logging
from typing import Any
from sqlalchemy import text

logger = logging.getLogger("vision-ai")


def safe_fps(fps: int | None, default: int = 30) -> int:
    """
    Validates that FPS is an integer between 5 and 60.
    Falls back to `default` with a log warning on invalid inputs.
    """
    if isinstance(fps, int) and 5 <= fps <= 60:
        return fps
    logger.warning(f"[LIMITS] Invalid or out-of-range FPS '{fps}', falling back to {default}")
    return default


def get_supported_fps_options(resolution: str | None = None) -> list[int]:
    """
    Returns supported FPS options for the camera pipeline.
    OAK-D / Sony IMX586 with DepthAI RVC4 supports up to 60 FPS for 1080p and 720p.
    """
    return [5, 10, 15, 20, 25, 30, 60]


def compute_camera_control_limits(
    camera_id: int,
    configured_fps: int | None,
    resolution: str | None = "1920x1080",
) -> dict[str, Any]:
    """
    Computes dynamic three-zone limits for camera controls based on configured FPS.
    Integer microsecond calculations are used to avoid float rounding errors.
    """
    fps = safe_fps(configured_fps, default=30)
    frame_period_us = 1_000_000 // fps
    recommended_max_exposure_us = 950_000 // fps
    default_exposure_us = min(8000, recommended_max_exposure_us)
    fps_options = get_supported_fps_options(resolution)

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
                "source": "hardware",
                "scale": "log",
                "quantized": True,
                "verified": True,
                "hardware_min": 65,
                "hardware_max": 16585,
                "recommended_min": 100,
                "recommended_max": 6400,
                "default": 400,
                "step": 1,
                "warnings": [
                    {
                        "op": "gt",
                        "value": 6400,
                        "level": "warning",
                        "message": "High sensor noise and digital grain",
                    }
                ],
            },
            "exposure": {
                "source": "hardware",
                "scale": "log",
                "quantized": False,
                "verified": False,  # 86us floor verified; long-exposure FPS drop uncalibrated
                "unit": "us",
                "display_unit": "ms",
                "hardware_min": 86,
                "hardware_max": 1_000_000,
                "recommended_min": 100,
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
                "source": "hardware",
                "scale": "linear",
                "quantized": True,
                "verified": False,
                "hardware_min": 0,
                "hardware_max": 255,
                "recommended_min": 0,
                "recommended_max": 255,
                "default": 128,
                "step": 1,
                "warnings": [],
            },
            "contrast": {
                "source": "hardware",
                "scale": "linear",
                "quantized": True,
                "verified": False,
                "hardware_min": -10,
                "hardware_max": 10,
                "recommended_min": -5,
                "recommended_max": 8,
                "default": 0,
                "step": 1,
                "warnings": [
                    {
                        "op": "lt",
                        "value": -5,
                        "level": "info",
                        "message": "Low contrast creates a flat, washed-out image",
                    },
                    {
                        "op": "gt",
                        "value": 8,
                        "level": "warning",
                        "message": "Extreme contrast risks clipping specular highlights",
                    },
                ],
            },
            "brightness": {
                "source": "software",
                "scale": "linear",
                "quantized": False,
                "verified": False,  # Software LUT negative test pending
                "min": -50,
                "max": 50,
                "recommended_min": -20,
                "recommended_max": 20,
                "default": 0,
                "step": 1,
                "warnings": [
                    {
                        "op": "abs_gt",
                        "value": 20,
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
                # Read all cameras
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

