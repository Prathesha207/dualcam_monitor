from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Float
from app.core.database import Base


class Camera(Base):
    __tablename__ = "cameras"

    id = Column(Integer, primary_key=True, index=True)

    name = Column(String(100), nullable=False)

    ip_address = Column(String(255), nullable=True)

    # Resolution & Frame Rate
    resolution = Column(String(50), nullable=True)  
    fps = Column(Integer, default=30)  
    rotation_angle = Column(Integer, default=0)  
    
    # Mode
    control_mode = Column(String(20), default="auto")  
    
    # Manual Controls (ONLY used when manual mode)
    exposure = Column(Float, nullable=True)
    gain = Column(Float, nullable=True)
    focus = Column(Integer, nullable=True)

    brightness = Column(Integer, nullable=True)
    contrast = Column(Integer, nullable=True)

    # Auto Toggles
    auto_exposure = Column(Boolean, default=False)
    auto_focus = Column(Boolean, default=False)
    
    # Streaming & Recording
    stream_url = Column(String(500), nullable=True)
    recording_video_path = Column(String, nullable=True)
    recording_video_testing_path = Column(String, nullable=True)
    recording_format = Column(String(20), default="MP4")
    clip_duration_minutes = Column(Integer, default=1)

    is_enabled = Column(Boolean, default=True)

    created_at = Column(DateTime, default=datetime.utcnow)
