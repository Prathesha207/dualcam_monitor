from pydantic import BaseModel, Field, field_validator
from datetime import datetime
from typing import Optional, Literal


class CameraBase(BaseModel):
    name: str
    ip_address: Optional[str] = None

    resolution: Optional[str] = None
    fps: int = Field(default=30, ge=5, le=60)
    rotation_angle: int = Field(default=0, ge=0, le=360)

    # Mode
    control_mode: Literal["auto", "manual"] = "auto"

    @field_validator("control_mode", mode="before")
    @classmethod
    def sanitize_control_mode(cls, v):
        if not v:
            return "auto"
        s = str(v).strip().lower()
        return "manual" if s == "manual" else "auto"

    # Manual Controls
    exposure: Optional[float] = Field(default=None, ge=0, le=1000)
    gain: Optional[float] = Field(default=None, ge=0, le=16585)
    focus: Optional[int] = Field(default=None, ge=0, le=255)

    brightness: Optional[int] = Field(default=0, ge=-50, le=50)
    contrast: Optional[int] = Field(default=0, ge=-10, le=10)

    @field_validator("exposure", mode="before")
    @classmethod
    def sanitize_exposure(cls, v):
        if v is None:
            return None
        try:
            val = float(v)
            if val > 1000.0:  # Microseconds passed instead of milliseconds
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
            return 0
        try:
            val = int(round(float(v)))
            return max(-50, min(50, val))
        except (ValueError, TypeError):
            return 0

    @field_validator("contrast", mode="before")
    @classmethod
    def sanitize_contrast(cls, v):
        if v is None:
            return 0
        try:
            val = int(round(float(v)))
            if val > 10:  # Legacy 0..100 scale (where 50 was neutral)
                return max(-10, min(10, int(round((val - 50.0) / 5.0))))
            return max(-10, min(10, val))
        except (ValueError, TypeError):
            return 0

    @field_validator("fps", mode="before")
    @classmethod
    def sanitize_fps(cls, v):
        if v is None:
            return 30
        try:
            val = int(round(float(v)))
            return max(5, min(60, val))
        except (ValueError, TypeError):
            return 30

    @field_validator("clip_duration_minutes", mode="before")
    @classmethod
    def sanitize_clip_duration(cls, v):
        if v is None:
            return 1
        try:
            val = int(round(float(v)))
            return max(1, min(1440, val))
        except (ValueError, TypeError):
            return 1

    # Legacy status fields; camera autofocus and auto exposure are always off.
    auto_exposure: bool = False
    auto_focus: bool = False

    # Streaming & Recording
    stream_url: Optional[str] = None
    recording_video_path: Optional[str] = None
    recording_video_testing_path: Optional[str] = None
    recording_format: Optional[str] = "MP4"
    clip_duration_minutes: Optional[int] = Field(default=1, ge=1, le=1440)


class CameraCreate(CameraBase):
    is_enabled: bool = True


class CameraUpdate(BaseModel):
    name: Optional[str] = None
    ip_address: Optional[str] = None
    resolution: Optional[str] = None
    fps: Optional[int] = Field(default=None, ge=5, le=60)
    rotation_angle: Optional[int] = Field(default=None, ge=0, le=360)

    control_mode: Optional[Literal["auto", "manual"]] = None

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

    @field_validator("fps", mode="before")
    @classmethod
    def sanitize_fps(cls, v):
        if v is None:
            return None
        try:
            val = int(round(float(v)))
            return max(5, min(60, val))
        except (ValueError, TypeError):
            return None

    @field_validator("clip_duration_minutes", mode="before")
    @classmethod
    def sanitize_clip_duration(cls, v):
        if v is None:
            return None
        try:
            val = int(round(float(v)))
            return max(1, min(1440, val))
        except (ValueError, TypeError):
            return None

    auto_exposure: Optional[bool] = None
    auto_focus: Optional[bool] = None

    stream_url: Optional[str] = None
    is_enabled: Optional[bool] = None
    recording_video_path: Optional[str] = None
    recording_video_testing_path: Optional[str] = None
    recording_format: Optional[str] = None
    clip_duration_minutes: Optional[int] = Field(default=None, ge=1, le=1440)


class CameraResponse(CameraBase):
    id: int
    is_enabled: bool
    created_at: datetime

    class Config:
        from_attributes = True
