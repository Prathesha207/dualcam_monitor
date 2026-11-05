export type ThemeMode = 'pond-light' | 'pond-dark' | 'nature';

export type StreamSourceType = 'oak-camera' | 'usb-camera' | 'webcam';

export interface CameraConfig {
  id?: number;
  sourceName: string;
  resolution: '1920x1080' | '1280x720';
  targetFps: number;
  fps?: number;
  recordingFormat?: 'AVI' | 'MP4' | 'FFV1';
  recordingVideoPath?: string | null;
  clipDurationMinutes?: number;
  rotationAngle?: number;
  controlMode?: 'auto' | 'manual';
  exposure: number;
  gain?: number;
  focus?: number;
  focusAvailable?: boolean;
  brightness: number; // -50 to +50
  contrast: number; // -10 to +10
  iso: number;
  autoFocus: boolean;
  autoExposure?: boolean;
  connected: boolean;
  is_enabled?: boolean;
  connectionQuality?: 'Excellent' | 'Good' | 'Fair' | 'Poor';
  ipAddress: string;
  telemetry?: {
    iso?: number | null;
    exposure_us?: number | null;
    exposure_ms?: number | null;
    lens_position?: number | null;
    timestamp?: number | null;
  };
}

export interface ProcessStep {
  id: string;
  label: string;
  status: 'completed' | 'active' | 'pending' | 'error';
  timestamp?: string;
}

export interface LogEntry {
  id: string;
  timestamp: string;
  message: string;
  level: 'info' | 'success' | 'warn' | 'error';
}
