import React, { useRef, useState, useEffect, useMemo, useCallback } from 'react';
import type { CameraConfig } from '../types';
import { cameraService } from './service/cameraService';
import { useCanvasZoom } from '../hooks/useCanvasZoom';
import { ZoomControls } from './canvas/ZoomControls';
import { CameraTuningPopover } from './canvas/CameraTuningPopover';
import {
  Play,
  Square,
  Power,
  Maximize2,
  Minimize2,
  SlidersHorizontal,
  Settings2,
  Camera,
  AlertCircle,
  AlertTriangle,
  RefreshCw,
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
  connectionError?: string | null;
  onStartStream: (id: number) => void;
  onStopStream: (id: number) => void;
  onToggleRecord: (id: number) => void;
  onToggleEnable: (id: number, currentEnabled: boolean) => void;
  onExpandToggle: (id: number) => void;
  onOpenEdit: (camera: CameraConfig) => void;
  onOpenControls?: (camera: CameraConfig) => void;
  onUpdateLiveControls?: (id: number, partial: Partial<CameraConfig>) => void;
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
  connectionError = null,
  onStartStream,
  onStopStream,
  onToggleRecord,
  onToggleEnable,
  onExpandToggle,
  onOpenEdit,
  onOpenControls,
  onUpdateLiveControls,
  onSnapshot,
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const [streamError, setStreamError] = useState(false);
  const [streamCacheBuster, setStreamCacheBuster] = useState(Date.now());
  const [containerSize, setContainerSize] = useState({ width: 0, height: 0 });
  const [videoAspect, setVideoAspect] = useState(16 / 9);
  const [snapshotFlash, setSnapshotFlash] = useState(false);
  const [isTuningOpen, setIsTuningOpen] = useState(false);

  // Automatically close tuning popover if mode is not manual
  useEffect(() => {
    if (camera.controlMode !== 'manual') {
      setIsTuningOpen(false);
    }
  }, [camera.controlMode]);

  const cameraId = camera.id || index;
  const isEnabled = camera.is_enabled !== false;
  const isIpCamera = Boolean(
    camera.ipAddress &&
    camera.ipAddress.includes('.') &&
    !camera.ipAddress.toLowerCase().includes('usb')
  );

  // Canvas Zoom & Pan Hook (active when live stream is running)
  const {
    zoom,
    zoomIn,
    zoomOut,
    resetZoom,
    setZoomLevel,
    viewportRef,
    transformStyle,
    handleMouseDown,
    handleDoubleClick,
    cursorStyle,
  } = useCanvasZoom(isStreaming);

  // Synchronize containerRef and viewportRef to canvas DOM node
  const setCanvasRef = useCallback(
    (node: HTMLDivElement | null) => {
      containerRef.current = node;
      (viewportRef as React.MutableRefObject<HTMLDivElement | null>).current = node;
    },
    [viewportRef]
  );

  // Reset zoom to 1x when stream stops
  useEffect(() => {
    if (!isStreaming) {
      resetZoom();
    }
  }, [isStreaming, resetZoom]);

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
      className="relative flex flex-col h-full w-full rounded-2xl bg-[var(--bg-card)] border border-[var(--border-color)] transition-all duration-200 overflow-hidden shadow-xs select-none"
    >
      {/* ── 1. Card Top Header ────────────────────────────────────────── */}
      <div className="flex items-center justify-between px-3 sm:px-4 py-2.5 border-b border-[var(--border-color)] bg-[var(--bg-card-subtle)]/60 shrink-0 gap-2">
        
        {/* Left: Camera Identification, Status Badges & Hardware Details */}
        <div className="flex items-center gap-2.5 min-w-0">
          <div
            className={`flex items-center justify-center w-8 h-8 rounded-xl border shrink-0 transition-colors ${
              connectionError
                ? 'bg-rose-500/15 text-rose-600 dark:text-rose-400 border-rose-500/30'
                : 'bg-[var(--accent-pond-subtle)] text-[var(--accent-pond)] border-[var(--border-color)]'
            }`}
          >
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
              ) : isStarting ? (
                <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] font-bold bg-[var(--accent-pond-subtle)] text-[var(--accent-pond)] border border-[var(--accent-pond)]/30 shrink-0">
                  <Loader2 className="w-2.5 h-2.5 animate-spin" />
                  CONNECTING
                </span>
              ) : connectionError ? (
                <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] font-bold bg-rose-500/15 text-rose-600 dark:text-rose-400 border border-rose-500/30 shrink-0">
                  <span className="w-1.5 h-1.5 rounded-full bg-rose-500" />
                  UNREACHABLE
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

              {/* Active Recording Pill in Header with Live Ticking Duration */}
              {isRecording && (
                <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] font-mono font-bold bg-red-500/15 text-red-600 dark:text-red-400 border border-red-500/40 shrink-0 animate-pulse">
                  <span className="w-1.5 h-1.5 rounded-full bg-red-500 animate-ping" />
                  REC {formatDuration(recordingDuration)}
                </span>
              )}

              {/* Mode Badge (Auto / Manual) - Clickable to toggle between AUTO and MANUAL */}
              <button
                type="button"
                onClick={() => {
                  if (camera.controlMode !== 'manual') {
                    onUpdateLiveControls?.(cameraId, { controlMode: 'manual' });
                    setIsTuningOpen(true);
                  } else {
                    onUpdateLiveControls?.(cameraId, { controlMode: 'auto' });
                    setIsTuningOpen(false);
                  }
                }}
                title={
                  camera.controlMode === 'manual'
                    ? 'Mode: MANUAL (Click to switch to AUTO)'
                    : 'Mode: AUTO (Click to enable MANUAL tuning)'
                }
                className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-mono font-bold tracking-wide uppercase transition-all cursor-pointer active:scale-95 border ${
                  camera.controlMode === 'manual'
                    ? isTuningOpen
                      ? 'bg-cyan-500/20 text-cyan-700 dark:text-cyan-300 border-cyan-500/40 ring-1 ring-cyan-500/20 shadow-2xs'
                      : 'bg-cyan-500/10 text-cyan-600 dark:text-cyan-400 border-cyan-500/30 hover:bg-cyan-500/20'
                    : 'bg-[var(--bg-card)] text-[var(--text-secondary)] border-[var(--border-color)] hover:text-[var(--text-primary)] hover:border-[var(--accent-pond)]'
                } shrink-0`}
              >
                {camera.controlMode?.toUpperCase() || 'AUTO'}
              </button>
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

        {/* Right: Hardware Power Toggle - Show on Standby and Live Stream, Hide when Connecting or Unreachable */}
        {!isStarting && !connectionError && (
          <div className="flex items-center gap-2 shrink-0">
            <button
              onClick={() => onToggleEnable(cameraId, isEnabled)}
              title={
                isStreaming
                  ? 'Camera stream is active (Click to power down)'
                  : isEnabled
                    ? 'Camera in Standby (Click to power off)'
                    : 'Camera powered off (Click to power on)'
              }
              aria-label={
                isStreaming
                  ? 'Disable camera'
                  : isEnabled
                    ? 'Power off camera'
                    : 'Power on camera'
              }
              className={`flex items-center justify-center w-8 h-8 rounded-xl border transition-all cursor-pointer shadow-xs active:scale-95 ${
                isStreaming
                  ? 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border-emerald-500/30 hover:bg-emerald-500/20'
                  : isEnabled
                    ? 'bg-[var(--btn-secondary-bg)] hover:bg-amber-500/15 text-[var(--text-secondary)] hover:text-amber-500 border-[var(--border-color)] hover:border-amber-500/30'
                    : 'bg-amber-500/10 text-amber-600 dark:text-amber-400 border-amber-500/30 hover:bg-emerald-500/10 hover:text-emerald-500 hover:border-emerald-500/30'
              }`}
            >
              <Power className="w-3.5 h-3.5 stroke-[2.5]" />
            </button>
          </div>
        )}
      </div>

      {/* ── 2. Card Center Video Canvas ───────────────────────────────── */}
      <div
        ref={setCanvasRef}
        onMouseDown={isStreaming ? handleMouseDown : undefined}
        onDoubleClick={isStreaming ? handleDoubleClick : undefined}
        style={{ cursor: isStreaming ? cursorStyle : 'default' }}
        className="relative flex-1 min-h-[240px] sm:min-h-[300px] bg-black flex items-center justify-center overflow-hidden"
      >
        {/* Flash effect on snapshot */}
        {snapshotFlash && (
          <div className="absolute inset-0 z-30 bg-white/40 pointer-events-none animate-out fade-out duration-200" />
        )}

        {/* State 0: Connecting (When camera hardware is starting up / retrying) */}
        {!isStreaming && isStarting && (
          <div className="absolute inset-0 flex flex-col items-center justify-center text-center p-6 bg-[var(--bg-card)] select-none">
            <div className="w-12 h-12 rounded-2xl bg-[var(--accent-pond-subtle)] border border-[var(--border-color)] flex items-center justify-center text-[var(--accent-pond)] mb-3 shadow-xs">
              <Loader2 className="w-6 h-6 animate-spin text-[var(--accent-pond)]" />
            </div>
            <h4 className="font-bold text-sm sm:text-base text-[var(--text-primary)] mb-1">
              Connecting to {camera.sourceName || `Camera ${index}`}
            </h4>
            <p className="text-xs text-[var(--text-secondary)] max-w-xs">
              {isIpCamera
                ? `Establishing link to ${camera.ipAddress}...`
                : 'Initializing OAK hardware pipeline...'}
            </p>
          </div>
        )}

        {/* State A: Connection Error / Unreachable (Same clean styling as Standby) */}
        {!isStreaming && !isStarting && connectionError && (
          <div className="absolute inset-0 flex flex-col items-center justify-center text-center p-6 bg-[var(--bg-card)] select-none">
            <div className="w-12 h-12 rounded-2xl bg-rose-500/10 border border-rose-500/20 flex items-center justify-center text-rose-500 mb-3 shadow-xs">
              <AlertTriangle className="w-6 h-6 stroke-[1.75]" />
            </div>
            <h4 className="font-bold text-sm sm:text-base text-[var(--text-primary)] mb-1">
              Camera Unreachable
            </h4>
            <p className="text-xs text-[var(--text-secondary)] max-w-xs mb-4">
              {connectionError}
            </p>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => onOpenEdit(camera)}
                className="inline-flex items-center gap-1.5 h-8 px-3.5 rounded-xl bg-[var(--bg-card-subtle)] hover:bg-[var(--accent-pond-subtle)] text-[var(--accent-pond)] border border-[var(--border-color)] hover:border-[var(--accent-pond)] text-xs font-bold transition-all cursor-pointer shadow-xs active:scale-95"
              >
                <Settings2 className="w-3.5 h-3.5" />
                <span>Edit Camera IP</span>
              </button>
              <button
                type="button"
                onClick={() => onStartStream(cameraId)}
                disabled={isStarting}
                className="inline-flex items-center gap-1.5 h-8 px-3.5 rounded-xl bg-rose-600 hover:bg-rose-700 active:scale-95 text-white border border-rose-500 text-xs font-bold transition-all cursor-pointer shadow-xs disabled:opacity-50"
              >
                {isStarting ? (
                  <>
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    <span>Connecting...</span>
                  </>
                ) : (
                  <>
                    <RefreshCw className="w-3.5 h-3.5" />
                    <span>Retry</span>
                  </>
                )}
              </button>
            </div>
          </div>
        )}

        {/* State B: Hardware Disabled (No connection error) */}
        {!isStreaming && !isStarting && !connectionError && !isEnabled && (
          <div className="absolute inset-0 flex flex-col items-center justify-center text-center p-6 bg-[var(--bg-card)] select-none">
            <div className="w-12 h-12 rounded-2xl bg-amber-500/10 border border-amber-500/20 flex items-center justify-center text-amber-600 dark:text-amber-400 mb-3 shadow-xs">
              <Power className="w-6 h-6 stroke-[2]" />
            </div>
            <h4 className="font-bold text-sm sm:text-base text-[var(--text-primary)] mb-1">
              {camera.sourceName || `Camera ${index}`} Powered Off
            </h4>
            <p className="text-xs text-[var(--text-secondary)] max-w-xs">
              Hardware connection is released. Click the power button in header to connect.
            </p>
          </div>
        )}

        {/* State C: Hardware Enabled, Stream Stopped & Ready */}
        {!isStreaming && !isStarting && !connectionError && isEnabled && (
          <div className="absolute inset-0 flex flex-col items-center justify-center text-center p-6 bg-[var(--bg-card)] select-none">
            <div className="w-12 h-12 rounded-2xl bg-[var(--accent-pond-subtle)] border border-[var(--border-color)] flex items-center justify-center text-[var(--accent-pond)] mb-3 shadow-xs">
              <Radio className="w-6 h-6 stroke-[1.75]" />
            </div>
            <h4 className="font-bold text-sm sm:text-base text-[var(--text-primary)] mb-1">
              Live Stream Ready
            </h4>
            <p className="text-xs text-[var(--text-secondary)] max-w-xs">
              Stream is currently stopped. Click &quot;Start Stream&quot; below to begin live video.
            </p>
          </div>
        )}

        {/* State D: Live Video Feed (with smooth zoom and pan transform) */}
        {isEnabled && isStreaming && (
          <div
            className="relative shrink-0 flex items-center justify-center"
            style={{ ...fittedRect, ...transformStyle }}
          >
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

        {/* Floating Canvas Zoom Controls (Bottom Right of Video) */}
        {isEnabled && isStreaming && !streamError && !isTuningOpen && (
          <div
            className="absolute right-3 bottom-3 z-30"
            onMouseDown={(e) => e.stopPropagation()}
            onDoubleClick={(e) => e.stopPropagation()}
          >
            <ZoomControls
              zoom={zoom}
              onZoomIn={zoomIn}
              onZoomOut={zoomOut}
              onResetZoom={resetZoom}
              onSetZoom={setZoomLevel}
            />
          </div>
        )}

        {/* In-Canvas Camera Tuning Popover - ONLY when in manual mode */}
        {isTuningOpen && camera.controlMode === 'manual' && (
          <CameraTuningPopover
            cameraId={cameraId}
            cameraIndex={index}
            cameraName={camera.sourceName || `Camera 0${index}`}
            config={camera}
            isLive={isStreaming}
            onClose={() => setIsTuningOpen(false)}
            onUpdateConfig={(partial) => onUpdateLiveControls?.(cameraId, partial)}
          />
        )}
      </div>

      {/* ── 3. Card Bottom Toolbar ────────────────────────────────────── */}
      <div className="flex items-center justify-between px-3 sm:px-4 py-2 border-t border-[var(--border-color)] bg-[var(--bg-card)] shrink-0 gap-2">
        
        {/* Left: Stream Control & Record Control */}
        <div className="flex items-center gap-2">
          
          {/* Stream button: GREEN for start, WARNING AMBER for stop, DISABLED if hardware is off or unreachable */}
          {isStreaming ? (
            <button
              onClick={() => onStopStream(cameraId)}
              title="Stop live stream"
              className="inline-flex items-center gap-1.5 h-8 px-3.5 rounded-xl bg-amber-600 hover:bg-amber-700 active:scale-95 text-white border border-amber-500 text-xs font-bold transition-all cursor-pointer shadow-xs focus:outline-none focus-visible:outline-none focus:ring-0"
            >
              <Square className="w-3.5 h-3.5 fill-current" />
              <span>Stop Stream</span>
            </button>
          ) : (
            <button
              onClick={() => onStartStream(cameraId)}
              disabled={isStarting || Boolean(connectionError) || !isEnabled}
              title={
                isStarting
                  ? 'Connecting...'
                  : connectionError
                  ? 'Camera is unreachable. Click Retry on card or edit IP.'
                  : !isEnabled
                  ? 'Camera hardware is powered off. Power on to stream.'
                  : 'Start live stream'
              }
              className={`inline-flex items-center gap-1.5 h-8 px-3.5 rounded-xl text-xs font-bold border transition-all shadow-xs focus:outline-none focus-visible:outline-none focus:ring-0 ${
                isStarting
                  ? 'bg-emerald-600/70 text-white border-emerald-500 cursor-wait'
                  : connectionError || !isEnabled
                  ? 'bg-emerald-600 text-white border-emerald-500 opacity-40 cursor-not-allowed'
                  : 'bg-emerald-600 hover:bg-emerald-700 active:scale-95 text-white border-emerald-500 cursor-pointer'
              }`}
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

          {/* Record button: Solid red button (never white) */}
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
            className={`inline-flex items-center gap-1.5 h-8 px-3.5 rounded-xl text-xs font-bold border transition-all shadow-xs focus:outline-none focus-visible:outline-none focus:ring-0 ${
              !isStreaming || !isEnabled
                ? 'bg-red-600 text-white border-red-500 opacity-40 cursor-not-allowed'
                : isRecording
                ? 'bg-red-600 hover:bg-red-700 active:scale-95 text-white border-red-500 shadow-xs shadow-red-500/25 animate-pulse cursor-pointer'
                : 'bg-red-600 hover:bg-red-700 active:scale-95 text-white border-red-500 cursor-pointer'
            }`}
          >
            <span
              className={`w-2 h-2 rounded-full shrink-0 bg-white ${
                isRecording ? 'animate-ping' : ''
              }`}
            />
            <span className={isRecording ? 'font-mono' : ''}>
              {isRecording ? `REC ${formatDuration(recordingDuration)}` : 'Record'}
            </span>
          </button>
        </div>

        {/* Right: Utility Icon Buttons (Snapshot, Expand, Edit Config, Manual Controls) */}
        <div className="flex items-center gap-1.5">
          {/* Quick Snapshot button (Placed on the left of Expand) */}
          <button
            onClick={handleSnapshotClick}
            disabled={!isStreaming || !isEnabled}
            title={!isStreaming ? 'Start stream first to take snapshot' : 'Take instant high-resolution snapshot'}
            className="flex items-center justify-center w-8 h-8 rounded-xl bg-[var(--btn-secondary-bg)] hover:bg-[var(--btn-secondary-hover)] border border-[var(--btn-secondary-border)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-all cursor-pointer active:scale-95 shadow-xs disabled:opacity-35 disabled:cursor-not-allowed focus:outline-none"
          >
            <Camera className="w-3.5 h-3.5" />
          </button>

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

          {/* 3. Manual Live Controls (Sliders: Exposure, Gain, Focus, Brightness, Contrast) - ONLY IN MANUAL MODE */}
          {camera.controlMode === 'manual' && (
            <button
              onClick={() => {
                setIsTuningOpen((prev) => !prev);
                onOpenControls?.(camera);
              }}
              title={isTuningOpen ? 'Close image tuning' : 'Adjust exposure, gain, focus & brightness'}
              className={`flex items-center justify-center w-8 h-8 rounded-xl border transition-all cursor-pointer active:scale-95 shadow-xs ${
                isTuningOpen
                  ? 'bg-cyan-600 text-white border-cyan-500 shadow-md ring-2 ring-cyan-500/30'
                  : 'bg-[var(--btn-secondary-bg)] hover:bg-[var(--btn-secondary-hover)] border-[var(--btn-secondary-border)] text-[var(--text-primary)]'
              }`}
            >
              <SlidersHorizontal className="w-3.5 h-3.5" />
            </button>
          )}
        </div>
      </div>
    </div>
  );
};
