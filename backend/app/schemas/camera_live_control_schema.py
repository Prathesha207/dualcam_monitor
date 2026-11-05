# app/schemas/camera_live_control_schema.py

from pydantic import BaseModel, Field
from typing import Optional

class CameraLiveControl(BaseModel):
    control_mode: Optional[str] = None
    exposure: Optional[float] = Field(default=None, ge=0, le=1000)
    gain: Optional[float] = Field(default=None, ge=0, le=16585)
    focus: Optional[int] = Field(default=None, ge=0, le=255)
    brightness: Optional[int] = Field(default=None, ge=-50, le=50)
    contrast: Optional[int] = Field(default=None, ge=-10, le=10)
    save_to_db: Optional[bool] = None
    # Accepted for legacy clients, but camera AE/AF are always disabled.
    auto_focus: Optional[bool] = None
    autoFocus: Optional[bool] = None
    auto_exposure: Optional[bool] = None
    autoExposure: Optional[bool] = None
