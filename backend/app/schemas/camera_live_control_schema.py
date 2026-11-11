# app/schemas/camera_live_control_schema.py

from pydantic import BaseModel, Field, field_validator
from typing import Optional

class CameraLiveControl(BaseModel):
    control_mode: Optional[str] = None

    @field_validator("control_mode", mode="before")
    @classmethod
    def sanitize_control_mode(cls, v):
        if v is None:
            return None
        s = str(v).strip().lower()
        return "manual" if s == "manual" else "auto"

    exposure: Optional[float] = Field(default=None, ge=0, le=1000)
    gain: Optional[float] = Field(default=None, ge=0, le=16585)
    focus: Optional[int] = Field(default=None, ge=0, le=255)
    brightness: Optional[int] = Field(default=None, ge=-50, le=50)
    contrast: Optional[int] = Field(default=None, ge=-10, le=10)

    @field_validator("exposure", mode="before")
    @classmethod
    def sanitize_exposure(cls, v):
        if v is None:
            return None
        try:
            val = float(v)
            if val > 1000.0:
                val = val / 1000.0
            return max(0.0, min(1000.0, val))
        except (ValueError, TypeError):
            return None

    @field_validator("gain", mode="before")
    @classmethod
    def sanitize_gain(cls, v):
        if v is None:
            return None
        try:
            val = float(v)
            return max(0.0, min(16585.0, val))
        except (ValueError, TypeError):
            return None

    @field_validator("focus", mode="before")
    @classmethod
    def sanitize_focus(cls, v):
        if v is None:
            return None
        try:
            val = int(round(float(v)))
            return max(0, min(255, val))
        except (ValueError, TypeError):
            return None

    @field_validator("brightness", mode="before")
    @classmethod
    def sanitize_brightness(cls, v):
        if v is None:
            return None
        try:
            val = int(round(float(v)))
            return max(-50, min(50, val))
        except (ValueError, TypeError):
            return None

    @field_validator("contrast", mode="before")
    @classmethod
    def sanitize_contrast(cls, v):
        if v is None:
            return None
        try:
            val = int(round(float(v)))
            if val > 10:  # Legacy 0..100 scale (where 50 was neutral)
                return max(-10, min(10, int(round((val - 50.0) / 5.0))))
            return max(-10, min(10, val))
        except (ValueError, TypeError):
            return None

    save_to_db: Optional[bool] = None
    # Accepted for legacy clients, but camera AE/AF are always disabled.
    auto_focus: Optional[bool] = None
    autoFocus: Optional[bool] = None
    auto_exposure: Optional[bool] = None
    autoExposure: Optional[bool] = None
