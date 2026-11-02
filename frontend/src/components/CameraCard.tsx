import React, { useRef, useState, useEffect, useMemo } from 'react';
import type { CameraConfig } from '../types';
import { cameraService } from './service/cameraService';
import {
  Play,
  Square,
  Power,
  Maximize2,
  Minimize2,
  SlidersHorizontal,
  Settings2,
  Camera,
  VideoOff,
  AlertCircle,
  Loader2,
  Wifi,
  Usb,
  Radio,
} from 'lucide-react';

interface CameraCardProps {
  camera: CameraConfig;
  index: number;
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
  const [snapshotFlash, setSnapshotFlash] = useState(false);

  const cameraId = camera.id || index;
  const isEnabled = camera.is_enabled !== false;
  const isIpCamera = Boolean(
    camera.ipAddress &&
    camera.ipAddress.includes('.') &&
    !camera.ipAddress.toLowerCase().includes('usb')
  );

  // Resize observer to maintain proper video aspect ratio without distortion
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

  // Format recording timer: MM:SS or HH:MM:SS
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

  const handleSnapshotClick = () => {
    if (onSnapshot) {
      setSnapshotFlash(true);
      setTimeout(() => setSnapshotFlash(false), 200);
      onSnapshot(cameraId);
    }
  };

  return (
    <div
      className={`relative flex flex-col h-full w-full rounded-2xl bg-[var(--bg-card)] border transition-all duration-200 overflow-hidden shadow-xs select-none ${
        isControlsOpen
          ? 'border-[var(--accent-pond)] ring-2 ring-[var(--accent-pond)]/20'
          : 'border-[var(--border-color)]'
      }`}
    >
      {/* ── 1. Card Top Header ────────────────────────────────────────── */}
      <div className="flex items-center justify-between px-3 sm:px-4 py-2.5 border-b border-[var(--border-color)] bg-[var(--bg-card-subtle)]/60 shrink-0 gap-2">
        
        {/* Left: Camera Identification, Status Badges & Hardware Details */}
        <div className="flex items-center gap-2.5 min-w-0">
          <div className="flex items-center justify-center w-8 h-8 rounded-xl bg-[var(--accent-pond-subtle)] text-[var(--accent-pond)] border border-[var(--border-color)] shrink-0">
            {isIpCamera ? <Wifi className="w-4 h-4" /> : <Usb className="w-4 h-4" />}
          </div>

          <div className="flex flex-col min-w-0">
            {/* Title & Badges */}
            <div className="flex items-center gap-2 min-w-0">
              <span className="font-bold text-xs sm:text-sm text-[var(--text-primary)] truncate">
                {camera.sourceName || `Camera ${index}`}
              </span>

              {/* Streaming Status Pill */}
              {isStreaming ? (
                <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] font-bold bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 border border-emerald-500/30 shrink-0">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
                  LIVE
                </span>
              ) : isEnabled ? (
                <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold bg-[var(--bg-card)] text-[var(--text-secondary)] border border-[var(--border-color)] shrink-0">
                  STANDBY
                </span>
              ) : (
                <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold bg-amber-500/10 text-amber-600 dark:text-amber-400 border border-amber-500/20 shrink-0">
                  OFFLINE
                </span>
              )}

              {/* Mode Badge (Auto / Manual) */}
              <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[9px] font-mono font-bold tracking-wide uppercase bg-[var(--accent-pond-subtle)] text-[var(--accent-pond)] border border-[var(--border-color)] shrink-0">
                {camera.controlMode?.toUpperCase() || 'AUTO'}
              </span>
            </div>

            {/* Hardware & Stream Details Subtitle */}
            <div className="flex items-center gap-1.5 text-[10px] sm:text-[11px] text-[var(--text-secondary)] font-mono truncate mt-0.5">
              <span>{isIpCamera ? `IP: ${camera.ipAddress}` : 'USB 3.0'}</span>
              <span>•</span>
              <span>{camera.resolution || '1080p'} @ {camera.targetFps || 30} FPS</span>
              <span>•</span>
              <span className="uppercase">{camera.recordingFormat || 'MP4'}</span>
            </div>
          </div>
        </div>

        {/* Right: Record Button & Hardware Enable/Disable Toggle */}
        <div className="flex items-center gap-2 shrink-0">
          
          {/* Record button: enabled only when live streaming */}
          <button
            onClick={() => onToggleRecord(cameraId)}
            disabled={!isStreaming || !isEnabled}
            title={
              !isEnabled
                ? 'Camera hardware is disabled'
                : !isStreaming
                ? 'Start live stream first to record'
                : isRecording
                ? 'Stop recording'
                : 'Start recording'
            }
            className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-bold border transition-all cursor-pointer shadow-xs disabled:opacity-35 disabled:cursor-not-allowed ${
              isRecording
                ? 'bg-red-500/15 text-red-600 dark:text-red-400 border-red-500/40 shadow-xs shadow-red-500/20 animate-pulse'
                : 'bg-[var(--bg-card)] text-[var(--text-primary)] border-[var(--border-color)] hover:bg-[var(--bg-card-subtle)] hover:border-[var(--accent-pond)] active:scale-95'
            }`}
          >
            <span
              className={`w-2 h-2 rounded-full shrink-0 ${
                isRecording ? 'bg-red-500 animate-ping' : 'bg-red-500'
              }`}
            />
            <span className="font-mono">
              {isRecording ? `REC ${formatDuration(recordingDuration)}` : 'Record'}
            </span>
          </button>

          {/* Hardware Power Toggle */}
          <button
            onClick={() => onToggleEnable(cameraId, isEnabled)}
            title={isEnabled ? 'Hardware is ON (Click to power down)' : 'Hardware is OFF (Click to power up)'}
            className={`flex items-center justify-center w-8 h-8 rounded-xl border transition-all cursor-pointer shadow-xs active:scale-95 ${
              isEnabled
                ? 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border-emerald-500/30 hover:bg-emerald-500/20'
                : 'bg-amber-500/10 text-amber-600 dark:text-amber-400 border-amber-500/30 hover:bg-amber-500/20'
            }`}
          >
            <Power className="w-3.5 h-3.5 stroke-[2.5]" />
          </button>
        </div>
      </div>

      {/* ── 2. Card Center Video Canvas ───────────────────────────────── */}
      <div
        ref={containerRef}
        className="relative flex-1 min-h-[240px] sm:min-h-[300px] bg-black flex items-center justify-center overflow-hidden"
      >
        {/* Flash effect on snapshot */}
        {snapshotFlash && (
          <div className="absolute inset-0 z-30 bg-white/40 pointer-events-none animate-out fade-out duration-200" />
        )}

        {/* State A: Hardware Disabled */}
        {!isEnabled && (
          <div className="absolute inset-0 flex flex-col items-center justify-center text-center p-6 bg-[var(--bg-card)] select-none">
            <div className="w-12 h-12 rounded-2xl bg-amber-500/10 border border-amber-500/20 flex items-center justify-center text-amber-600 dark:text-amber-400 mb-3 shadow-xs">
              <Power className="w-6 h-6 stroke-[2]" />
            </div>
            <h4 className="font-bold text-sm sm:text-base text-[var(--text-primary)] mb-1">
              {camera.sourceName || `Camera ${index}`} Offline
            </h4>
            <p className="text-xs text-[var(--text-secondary)] max-w-xs mb-4">
              Hardware connection is released. All USB and video resources are freed.
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
            <div className="w-12 h-12 rounded-2xl bg-[var(--accent-pond-subtle)] border border-[var(--border-color)] flex items-center justify-center text-[var(--accent-pond)] mb-3 shadow-xs">
              <Radio className="w-6 h-6 stroke-[1.75]" />
            </div>
            <h4 className="font-bold text-sm sm:text-base text-[var(--text-primary)] mb-1">
              Live Stream Ready
            </h4>
            <p className="text-xs text-[var(--text-secondary)] max-w-xs mb-4">
              Camera hardware is connected. Click Start Stream below to begin real-time monitoring.
            </p>
            <button
              onClick={() => onStartStream(cameraId)}
              disabled={isStarting}
              className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-[var(--btn-primary-bg)] text-[var(--btn-primary-text)] font-bold text-xs sm:text-sm shadow-md hover:opacity-90 active:scale-95 cursor-pointer disabled:opacity-50"
            >
              {isStarting ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  <span>Connecting Stream...</span>
                </>
              ) : (
                <>
                  <Play className="w-4 h-4 fill-current" />
                  <span>Start Live Stream</span>
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
                streamError ? 'opacity-30' : 'opacity-100'
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

            {/* Overlays: Human-Understandable Live HUD Pill */}
            <div className="absolute top-3 left-3 flex items-center gap-2 pointer-events-none">
              <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-black/65 backdrop-blur-md text-white border border-white/20 shadow-lg text-xs font-semibold">
                <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
                <span className="font-bold tracking-wide">LIVE</span>
                <span className="text-white/40">•</span>
                <span className="text-white/90">
                  {camera.resolution === '1280x720' ? '720p HD' : '1080p FHD'}
                </span>
                <span className="text-white/40">•</span>
                <span className="font-mono text-white/90">{camera.targetFps || 30} FPS</span>
              </div>
            </div>

            {/* Recording Active HUD tag */}
            {isRecording && (
              <div className="absolute top-3 right-3 flex items-center gap-2 px-3 py-1 rounded-full bg-red-950/80 backdrop-blur-md text-white text-xs font-mono font-bold border border-red-500/50 shadow-lg shadow-red-900/40 pointer-events-none animate-pulse">
                <span className="w-2 h-2 rounded-full bg-red-500 animate-ping" />
                <span className="text-red-200">RECORDING</span>
                <span className="text-white font-bold">[{formatDuration(recordingDuration)}]</span>
              </div>
            )}

            {/* Error Reconnect Overlay */}
            {streamError && (
              <div className="absolute inset-0 flex flex-col items-center justify-center bg-black/80 text-white p-4">
                <AlertCircle className="w-8 h-8 text-amber-400 mb-2 animate-bounce" />
                <span className="text-sm font-bold">Waiting for camera video frames...</span>
                <span className="text-xs text-white/60 mt-1">Re-establishing high-speed video link</span>
              </div>
            )}
          </div>
        )}
      </div>

      {/* ── 3. Card Bottom Toolbar ────────────────────────────────────── */}
      <div className="flex items-center justify-between px-3 sm:px-4 py-2 border-t border-[var(--border-color)] bg-[var(--bg-card)] shrink-0 gap-2">
        
        {/* Left: Start / Stop Stream Toggle & Snapshot */}
        <div className="flex items-center gap-2">
          {isStreaming ? (
            <button
              onClick={() => onStopStream(cameraId)}
              title="Stop live stream"
              className="inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-xl bg-[var(--btn-secondary-bg)] hover:bg-[var(--btn-secondary-hover)] border border-[var(--btn-secondary-border)] text-xs font-bold text-[var(--btn-secondary-text)] transition-all cursor-pointer active:scale-95 shadow-xs"
            >
              <Square className="w-3.5 h-3.5 fill-current" />
              <span>Stop Stream</span>
            </button>
          ) : (
            <button
              onClick={() => onStartStream(cameraId)}
              disabled={!isEnabled || isStarting}
              title={!isEnabled ? 'Enable camera first' : 'Start live stream'}
              className="inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-xl bg-[var(--btn-primary-bg)] text-[var(--btn-primary-text)] hover:opacity-90 border border-transparent text-xs font-bold transition-all cursor-pointer active:scale-95 shadow-xs disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {isStarting ? (
                <>
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  <span>Connecting...</span>
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
          {isStreaming && (
            <button
              onClick={handleSnapshotClick}
              title="Take instant high-resolution snapshot"
              className="flex items-center justify-center w-8 h-8 rounded-xl bg-[var(--btn-secondary-bg)] hover:bg-[var(--btn-secondary-hover)] border border-[var(--btn-secondary-border)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-all cursor-pointer active:scale-95 shadow-xs"
            >
              <Camera className="w-3.5 h-3.5" />
            </button>
          )}
        </div>

        {/* Right: 3 Utility Icon Buttons from Sketch (Expand, Edit Config, Manual Controls) */}
        <div className="flex items-center gap-1.5">
          
          {/* 1. Expand / Fullscreen */}
          <button
            onClick={() => onExpandToggle(cameraId)}
            title={isExpanded ? 'Minimize back to dual view' : 'Expand this camera to full canvas'}
            className="flex items-center justify-center w-8 h-8 rounded-xl bg-[var(--btn-secondary-bg)] hover:bg-[var(--btn-secondary-hover)] border border-[var(--btn-secondary-border)] text-[var(--text-primary)] transition-all cursor-pointer active:scale-95 shadow-xs"
          >
            {isExpanded ? <Minimize2 className="w-3.5 h-3.5" /> : <Maximize2 className="w-3.5 h-3.5" />}
          </button>

          {/* 2. Edit Camera Config */}
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
