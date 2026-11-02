export type ThemeMode = 'pond-light' | 'pond-dark' | 'nature';

export type StreamSourceType = 'oak-camera' | 'usb-camera' | 'webcam';

export interface CameraConfig {
  id?: number;
  sourceName: string;
  resolution: '1920x1080' | '1280x720';
  targetFps: number;
  recordingFormat?: 'AVI' | 'MP4' | 'FFV1';
  recordingVideoPath?: string | null;
  rotationAngle?: number;
  controlMode?: 'auto' | 'manual';
  exposure: number; // 0 - 100
  gain?: number;
  focus?: number;
  focusAvailable?: boolean;
  brightness: number; // -50 to +50
  contrast: number; // 0 to 100
  iso: number;
  autoFocus: boolean;
  autoExposure?: boolean;
  connected: boolean;
  is_enabled?: boolean;
  connectionQuality?: 'Excellent' | 'Good' | 'Fair' | 'Poor';
  ipAddress: string;
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
