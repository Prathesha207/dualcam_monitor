from typing import Optional
from pydantic import BaseModel


# ================= START =================
class StartRecordingRequest(BaseModel):
    session_id: str
    recording_format: Optional[str] = None
    camera_id: Optional[int] = None


# ================= FRAME (optional / keep if needed) =================
class FrameRequest(BaseModel):
    session_id: str
    frame: str
    camera_id: Optional[int] = None


# ================= STOP =================
class StopRecordingRequest(BaseModel):
    session_id: str
    camera_id: Optional[int] = None
