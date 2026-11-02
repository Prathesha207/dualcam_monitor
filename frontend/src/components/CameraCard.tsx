import React, { useRef, useState, useEffect, useMemo } from 'react';
import type { CameraConfig } from '../types';
import { cameraService } from './service/cameraService';
import {
  Play,
  Square,
  Circle,
  Power,
  Maximize2,
  Minimize2,
  SlidersHorizontal,
  Settings2,
  Camera,
  VideoOff,
  AlertCircle,
  Loader2,
} from 'lucide-react';

interface CameraCardProps {
  camera: CameraConfig;
  index: number; // 1 or 2
  isStreaming: boolean;
  isStarting?: boolean;
  isRecording: boolean;
  recordingDuration?: number;
  isExpanded?: boolean;
  isControlsOpen?: boolean;
  onStartStream: (id: number) => void;
  onStopStream: (id: number) => void;
  onToggleRecord: (id: number) => void;
  onToggleEnable: (id: number, currentEnabled: boolean) => void;
  onExpandToggle: (id: number) => void;
  onOpenEdit: (camera: CameraConfig) => void;
  onOpenControls: (camera: CameraConfig) => void;
  onSnapshot?: (id: number) => void;
}

export const CameraCard: React.FC<CameraCardProps> = ({
  camera,
  index,
  isStreaming,
  isStarting = false,
  isRecording,
  recordingDuration = 0,
  isExpanded = false,
  isControlsOpen = false,
  onStartStream,
  onStopStream,
  onToggleRecord,
  onToggleEnable,
  onExpandToggle,
  onOpenEdit,
  onOpenControls,
  onSnapshot,
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const [streamError, setStreamError] = useState(false);
  const [streamCacheBuster, setStreamCacheBuster] = useState(Date.now());
  const [containerSize, setContainerSize] = useState({ width: 0, height: 0 });
  const [videoAspect, setVideoAspect] = useState(16 / 9);

  const cameraId = camera.id || index;
  const isEnabled = camera.is_enabled !== false;

  // Aspect ratio fitting
  useEffect(() => {
    if (!containerRef.current) return;
    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        if (entry.contentRect.width > 0 && entry.contentRect.height > 0) {
          setContainerSize({
            width: entry.contentRect.width,
            height: entry.contentRect.height,
          });
        }
      }
    });
    observer.observe(containerRef.current);
    return () => observer.disconnect();
  }, []);

  const fittedRect = useMemo(() => {
    const { width: cW, height: cH } = containerSize;
    if (cW <= 0 || cH <= 0) return { width: '100%', height: '100%' };
    const containerAspect = cW / cH;
    if (containerAspect > videoAspect) {
      const targetW = Math.round(cH * videoAspect);
      return { width: `${targetW}px`, height: `${cH}px` };
    } else {
      const targetH = Math.round(cW / videoAspect);
      return { width: `${cW}px`, height: `${targetH}px` };
    }
  }, [containerSize, videoAspect]);

  // Format recording timer: HH:MM:SS
  const formatDuration = (secs: number) => {
    const hrs = Math.floor(secs / 3600);
    const mins = Math.floor((secs % 3600) / 60);
    const s = secs % 60;
    if (hrs > 0) {
      return `${String(hrs).padStart(2, '0')}:${String(mins).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
    }
    return `${String(mins).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
  };

  const streamUrl = `${cameraService.getStreamUrl(camera.id)}?t=${streamCacheBuster}`;

  return (
    <div
      className={`relative flex flex-col h-full w-full rounded-2xl bg-[var(--bg-card)] border transition-all duration-200 overflow-hidden shadow-xs select-none ${
        isControlsOpen
          ? 'border-[var(--accent-pond)] ring-2 ring-[var(--accent-pond)]/20'
          : 'border-[var(--border-color)]'
      }`}
    >
      {/* ── 1. Card Top Header ────────────────────────────────────────── */}
      <div className="flex items-center justify-between px-3 sm:px-4 py-2 border-b border-[var(--border-color)] bg-[var(--bg-card-subtle)]/50 shrink-0 gap-2">
        
        {/* Left: Camera details */}
        <div className="flex items-center gap-2 min-w-0">
          <div className="flex flex-col min-w-0">
            <div className="flex items-center gap-1.5 min-w-0">
              <span className="font-bold text-xs sm:text-sm text-[var(--text-primary)] truncate">
                {camera.sourceName || `Camera ${index}`}
              </span>
              <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[9px] font-mono font-bold uppercase bg-[var(--bg-card)] border border-[var(--border-color)] text-[var(--text-secondary)] shrink-0">
                CAM-{index} • {camera.controlMode?.toUpperCase() || 'AUTO'}
              </span>
            </div>
            <div className="flex items-center gap-2 text-[10px] sm:text-[11px] text-[var(--text-secondary)] font-mono truncate">
              <span>{camera.ipAddress?.includes('.') ? `IP: ${camera.ipAddress}` : 'USB Device'}</span>
              <span>•</span>
              <span>{camera.resolution || '1080p'} @ {camera.targetFps || 30} FPS</span>
            </div>
          </div>
        </div>

        {/* Right: Record Button & Hardware Enable/Disable Toggle */}
        <div className="flex items-center gap-1.5 sm:gap-2 shrink-0">
          
          {/* Record button: enabled only when streaming */}
          <button
            onClick={() => onToggleRecord(cameraId)}
            disabled={!isStreaming || !isEnabled}
            title={
              !isEnabled
                ? 'Camera hardware is disabled'
                : !isStreaming
                ? 'Start stream to enable recording'
                : isRecording
                ? 'Stop recording'
                : 'Start recording'
            }
            className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-xl text-xs font-bold border transition-all cursor-pointer shadow-xs disabled:opacity-40 disabled:cursor-not-allowed ${
              isRecording
                ? 'bg-[var(--status-anomaly-bg)] text-[var(--status-anomaly-text)] border-[var(--status-anomaly-border)] animate-pulse'
                : 'bg-[var(--bg-card)] text-[var(--text-primary)] border-[var(--border-color)] hover:bg-[var(--bg-card-subtle)] active:scale-95'
            }`}
          >
            <span
              className={`w-2 h-2 rounded-full shrink-0 ${
                isRecording ? 'bg-[var(--status-anomaly-text)] animate-ping' : 'bg-red-500'
              }`}
            />
            <span className="font-mono">
              {isRecording ? `REC ${formatDuration(recordingDuration)}` : 'Record'}
            </span>
          </button>

          {/* Hardware Enable / Disable Power Toggle */}
          <button
            onClick={() => onToggleEnable(cameraId, isEnabled)}
            title={isEnabled ? 'Hardware is Enabled (Click to disable device)' : 'Hardware is Disabled (Click to enable device)'}
            className={`flex items-center justify-center w-7 h-7 rounded-xl border transition-all cursor-pointer shadow-xs active:scale-95 ${
              isEnabled
                ? 'bg-[var(--status-normal-bg)] text-[var(--status-normal-text)] border-[var(--status-normal-border)]'
                : 'bg-[var(--status-anomaly-bg)] text-[var(--status-anomaly-text)] border-[var(--status-anomaly-border)]'
            }`}
          >
            <Power className="w-3.5 h-3.5 stroke-[2.5]" />
          </button>
        </div>
      </div>

      {/* ── 2. Card Center Video Canvas ───────────────────────────────── */}
      <div
        ref={containerRef}
        className="relative flex-1 min-h-[220px] sm:min-h-[280px] bg-black flex items-center justify-center overflow-hidden"
      >
        {/* State A: Hardware Disabled */}
        {!isEnabled && (
          <div className="absolute inset-0 flex flex-col items-center justify-center text-center p-6 bg-[var(--bg-card)] select-none">
            <div className="w-12 h-12 rounded-2xl bg-[var(--bg-card-subtle)] border border-[var(--border-color)] flex items-center justify-center text-[var(--text-secondary)] mb-3">
              <Power className="w-6 h-6 stroke-[1.75]" />
            </div>
            <h4 className="font-bold text-sm sm:text-base text-[var(--text-primary)] mb-1">
              {camera.sourceName || `Camera ${index}`} Hardware Disabled
            </h4>
            <p className="text-xs text-[var(--text-secondary)] max-w-xs mb-4">
              Device connection is released. Click the power button to reconnect hardware.
            </p>
            <button
              onClick={() => onToggleEnable(cameraId, false)}
              className="inline-flex items-center gap-1.5 px-4 py-2 rounded-xl bg-[var(--btn-primary-bg)] text-[var(--btn-primary-text)] font-bold text-xs shadow-xs hover:opacity-90 active:scale-95 cursor-pointer"
            >
              <Power className="w-3.5 h-3.5" />
              <span>Enable Hardware</span>
            </button>
          </div>
        )}

        {/* State B: Hardware Enabled, but Stream Stopped */}
        {isEnabled && !isStreaming && (
          <div className="absolute inset-0 flex flex-col items-center justify-center text-center p-6 bg-[var(--bg-card)] select-none">
            <div className="w-12 h-12 rounded-2xl bg-[var(--bg-card-subtle)] border border-[var(--border-color)] flex items-center justify-center text-[var(--text-secondary)] mb-3">
              <VideoOff className="w-6 h-6 stroke-[1.75]" />
            </div>
            <h4 className="font-bold text-sm sm:text-base text-[var(--text-primary)] mb-1">
              {camera.sourceName || `Camera ${index}`} Stream Stopped
            </h4>
            <p className="text-xs text-[var(--text-secondary)] max-w-xs mb-4">
              Click &quot;Start Stream&quot; below to begin streaming the live video feed.
            </p>
            <button
              onClick={() => onStartStream(cameraId)}
              disabled={isStarting}
              className="inline-flex items-center gap-1.5 px-5 py-2.5 rounded-xl bg-[var(--status-normal-bg)] text-[var(--status-normal-text)] border border-[var(--status-normal-border)] font-bold text-xs sm:text-sm shadow-xs hover:opacity-90 active:scale-95 cursor-pointer disabled:opacity-50"
            >
              {isStarting ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  <span>Connecting...</span>
                </>
              ) : (
                <>
                  <Play className="w-4 h-4 fill-current" />
                  <span>Start Stream</span>
                </>
              )}
            </button>
          </div>
        )}

        {/* State C: Live Video Feed */}
        {isEnabled && isStreaming && (
          <div className="relative shrink-0 flex items-center justify-center" style={fittedRect}>
            <img
              crossOrigin="anonymous"
              src={streamUrl}
              className={`w-full h-full object-contain pointer-events-none transition-opacity duration-200 ${
                streamError ? 'opacity-40' : 'opacity-100'
              }`}
              alt={`Live feed from Camera ${index}`}
              onLoad={(e) => {
                const img = e.target as HTMLImageElement;
                if (img.naturalWidth && img.naturalHeight) {
                  const aspect = img.naturalWidth / img.naturalHeight;
                  setVideoAspect((prev) => (prev !== aspect ? aspect : prev));
                }
                setStreamError(false);
              }}
              onError={() => {
                setStreamError(true);
                setTimeout(() => setStreamCacheBuster(Date.now()), 2000);
              }}
            />

            {/* Overlays: LIVE Badge */}
            <div className="absolute top-2.5 left-2.5 flex items-center gap-1.5 pointer-events-none">
              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-lg bg-black/70 backdrop-blur-md text-[10px] font-mono font-bold text-white border border-white/20">
                <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
                LIVE
              </span>
              <span className="inline-flex items-center px-1.5 py-0.5 rounded-lg bg-black/70 backdrop-blur-md text-[10px] font-mono text-white/90 border border-white/20">
                {camera.targetFps || 30} FPS
              </span>
            </div>

            {/* Recording Active HUD tag */}
            {isRecording && (
              <div className="absolute top-2.5 right-2.5 flex items-center gap-1 px-2 py-0.5 rounded-lg bg-red-600/90 backdrop-blur-md text-white text-[10px] font-mono font-bold border border-red-400 pointer-events-none animate-pulse">
                <span className="w-1.5 h-1.5 rounded-full bg-white" />
                <span>REC {formatDuration(recordingDuration)}</span>
              </div>
            )}

            {/* Error Reconnect Overlay */}
            {streamError && (
              <div className="absolute inset-0 flex flex-col items-center justify-center bg-black/75 text-white p-4">
                <AlertCircle className="w-8 h-8 text-amber-400 mb-2" />
                <span className="text-xs font-semibold">Connecting to camera feed...</span>
              </div>
            )}
          </div>
        )}
      </div>

      {/* ── 3. Card Bottom Toolbar ────────────────────────────────────── */}
      <div className="flex items-center justify-between px-3 sm:px-4 py-2 border-t border-[var(--border-color)] bg-[var(--bg-card)] shrink-0 gap-2">
        
        {/* Left: Start / Stop Stream Toggle */}
        <div className="flex items-center gap-2">
          {isStreaming ? (
            <button
              onClick={() => onStopStream(cameraId)}
              title="Stop live stream"
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-[var(--btn-secondary-bg)] hover:bg-[var(--btn-secondary-hover)] border border-[var(--btn-secondary-border)] text-xs font-bold text-[var(--btn-secondary-text)] transition-all cursor-pointer active:scale-95 shadow-xs"
            >
              <Square className="w-3.5 h-3.5 fill-current" />
              <span>Stop Stream</span>
            </button>
          ) : (
            <button
              onClick={() => onStartStream(cameraId)}
              disabled={!isEnabled || isStarting}
              title={!isEnabled ? 'Enable camera first' : 'Start live stream'}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-[var(--status-normal-bg)] text-[var(--status-normal-text)] hover:opacity-90 border border-[var(--status-normal-border)] text-xs font-bold transition-all cursor-pointer active:scale-95 shadow-xs disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {isStarting ? (
                <>
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  <span>Starting...</span>
                </>
              ) : (
                <>
                  <Play className="w-3.5 h-3.5 fill-current" />
                  <span>Start Stream</span>
                </>
              )}
            </button>
          )}

          {/* Quick Snapshot button */}
          {onSnapshot && isStreaming && (
            <button
              onClick={() => onSnapshot(cameraId)}
              title="Take instant snapshot"
              className="flex items-center justify-center w-8 h-8 rounded-xl bg-[var(--btn-secondary-bg)] hover:bg-[var(--btn-secondary-hover)] border border-[var(--btn-secondary-border)] text-[var(--text-secondary)] transition-all cursor-pointer active:scale-95 shadow-xs"
            >
              <Camera className="w-3.5 h-3.5" />
            </button>
          )}
        </div>

        {/* Right: 3 Utility Icon Buttons from Sketch (Expand, Edit Config, Manual Controls) */}
        <div className="flex items-center gap-1 sm:gap-1.5">
          
          {/* 1. Expand / Fullscreen */}
          <button
            onClick={() => onExpandToggle(cameraId)}
            title={isExpanded ? 'Minimize back to dual view' : 'Expand this camera to full canvas'}
            className="flex items-center justify-center w-8 h-8 rounded-xl bg-[var(--btn-secondary-bg)] hover:bg-[var(--btn-secondary-hover)] border border-[var(--btn-secondary-border)] text-[var(--text-primary)] transition-all cursor-pointer active:scale-95 shadow-xs"
          >
            {isExpanded ? <Minimize2 className="w-3.5 h-3.5" /> : <Maximize2 className="w-3.5 h-3.5" />}
          </button>

          {/* 2. Edit Camera Config (resolution, fps, name, format, folder path, device re-assignment) */}
          <button
            onClick={() => onOpenEdit(camera)}
            title="Edit camera parameters, resolution, FPS, format & device"
            className="flex items-center justify-center w-8 h-8 rounded-xl bg-[var(--btn-secondary-bg)] hover:bg-[var(--btn-secondary-hover)] border border-[var(--btn-secondary-border)] text-[var(--text-primary)] transition-all cursor-pointer active:scale-95 shadow-xs"
          >
            <Settings2 className="w-3.5 h-3.5" />
          </button>

          {/* 3. Manual Live Controls (Sliders: Exposure, Gain, Focus, Brightness, Contrast) */}
          <button
            onClick={() => onOpenControls(camera)}
            title={isControlsOpen ? 'Close image controls' : 'Adjust exposure, gain, focus & brightness'}
            className={`flex items-center justify-center w-8 h-8 rounded-xl border transition-all cursor-pointer active:scale-95 shadow-xs ${
              isControlsOpen
                ? 'bg-[var(--accent-pond)] text-white border-[var(--accent-pond)] shadow-md'
                : 'bg-[var(--btn-secondary-bg)] hover:bg-[var(--btn-secondary-hover)] border-[var(--btn-secondary-border)] text-[var(--text-primary)]'
            }`}
          >
            <SlidersHorizontal className="w-3.5 h-3.5" />
          </button>

        </div>
      </div>
    </div>
  );
};

