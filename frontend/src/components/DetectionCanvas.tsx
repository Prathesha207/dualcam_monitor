import React, { useRef, useState, useCallback, useEffect, useMemo } from 'react';
import type { CameraConfig } from '../types';
import { getApiBaseUrl } from '../lib/api';
import { showToast } from '../lib/toast';
import { cameraService } from './service/cameraService';

// Extracted Canvas Components
import { CameraOfflineCard } from './canvas/CameraOfflineCard';
import { CameraStandbyCard } from './canvas/CameraStandbyCard';
import { TopToolbar } from './canvas/TopToolbar';
import { ZoomControls } from './canvas/ZoomControls';

// Extracted Canvas Hooks
import { useFullscreen } from '../hooks/useFullscreen';
import { useCanvasZoom } from '../hooks/useCanvasZoom';

interface CameraStreamCanvasProps {
  isStreaming?: boolean;
  onStartStream?: () => void;
  onStopStream?: () => void;
  isCameraConnected?: boolean;
  isDeviceDetected?: boolean;
  cameraStartingState?: 'idle' | 'waking_camera' | 'waiting_frame' | 'ready';
  cameraError?: string | null;
  onRetryConnection?: () => void;
  isRecording?: boolean;
  recordingDuration?: number;
  fps?: number;
  cameraConfig?: CameraConfig;
  onSnapshot?: () => void;
}

export const DetectionCanvas: React.FC<CameraStreamCanvasProps> = ({
  isStreaming = false,
  onStartStream,
  isCameraConnected = false,
  isDeviceDetected = false,
  cameraStartingState = 'ready',
  cameraError = null,
  onRetryConnection,
  isRecording = false,
  recordingDuration = 0,
  fps = 30,
  cameraConfig,
  onSnapshot,
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const cameraImgRef = useRef<HTMLImageElement>(null);
  const [videoAspect, setVideoAspect] = useState<number>(16 / 9);
  const [streamError, setStreamError] = useState<boolean>(false);
  const [streamCacheBuster, setStreamCacheBuster] = useState<number>(Date.now());
  const retryTimeoutRef = useRef<NodeJS.Timeout | null>(null);

  // Fullscreen management
  const { isFullscreen, toggleFullscreen } = useFullscreen(containerRef);

  // Responsive aspect-ratio container fitting
  const [containerSize, setContainerSize] = useState<{ width: number; height: number }>({ width: 0, height: 0 });

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
    if (cW <= 0 || cH <= 0) {
      return { width: '100%', height: '100%' };
    }
    const containerAspect = cW / cH;
    if (containerAspect > videoAspect) {
      const targetW = Math.round(cH * videoAspect);
      return { width: `${targetW}px`, height: `${cH}px` };
    } else {
      const targetH = Math.round(cW / videoAspect);
      return { width: `${cW}px`, height: `${targetH}px` };
    }
  }, [containerSize, videoAspect]);

  // Pan & Zoom controls
  const {
    zoom,
    transformStyle,
    cursorStyle,
    viewportRef,
    handleMouseDown,
    handleDoubleClick,
    zoomIn,
    zoomOut,
    resetZoom,
    setZoomLevel,
  } = useCanvasZoom(isStreaming);

  // Snapshot capture handler
  const handleSnapshot = useCallback(async () => {
    try {
      const baseUrl = getApiBaseUrl();
      const res = await fetch(`${baseUrl}/oak/snapshot?t=${Date.now()}`);
      if (!res.ok) throw new Error('Snapshot failed');
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `snapshot_${new Date().toISOString().replace(/[:.]/g, '-')}.jpg`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      showToast('success', 'Snapshot downloaded');
    } catch {
      showToast('error', 'Failed to capture snapshot');
    }
  }, []);

  const streamUrl = `${getApiBaseUrl()}/oak/stream?t=${streamCacheBuster}`;

  return (
    <div
      ref={containerRef}
      id="camera-stream-viewport"
      className={`relative w-full flex-1 h-full min-h-[350px] lg:min-h-0 overflow-hidden border select-none group transition-colors duration-200 ${
        isFullscreen ? 'rounded-none border-none' : 'rounded-3xl'
      } border-[var(--border-color)] shadow-sm`}
      style={{
        backgroundColor: !isCameraConnected ? 'var(--bg-card)' : '#000000',
        ...(isFullscreen ? { width: '100%', height: '100%', minHeight: '100vh', maxHeight: '100vh' } : {}),
      }}
    >
      {/* Offline Card */}
      {!isCameraConnected && (
        <CameraOfflineCard
          onRetryConnection={
            onRetryConnection ||
            (async () => {
              try {
                await cameraService.start();
                await cameraService.startStream();
              } catch (e) {
                console.error('Retry connection failed:', e);
              }
            })
          }
          errorMessage={cameraError}
          isDeviceDetected={isDeviceDetected}
          isConnecting={cameraStartingState === 'waking_camera' || cameraStartingState === 'waiting_frame'}
        />
      )}

      {/* Standby Card (Camera connected, but stream not started) */}
      {isCameraConnected && !isStreaming && (
        <CameraStandbyCard onStartStream={onStartStream} />
      )}

      {/* Live Video Viewport */}
      {isCameraConnected && isStreaming && (
        <div
          ref={viewportRef}
          onMouseDown={handleMouseDown}
          onDoubleClick={handleDoubleClick}
          className="absolute inset-0 flex items-center justify-center pointer-events-auto bg-black overflow-hidden select-none"
          style={{ cursor: cursorStyle }}
        >
          <div
            className="relative shrink-0"
            style={{
              ...fittedRect,
              ...transformStyle,
            }}
          >
            <img
              ref={cameraImgRef}
              crossOrigin="anonymous"
              src={streamUrl}
              className={`absolute inset-0 z-0 h-full w-full pointer-events-none rounded bg-black object-fill ${
                streamError ? 'opacity-50' : 'opacity-100'
              }`}
              alt="Live Camera Feed"
              onLoad={(e) => {
                const tgt = e.target as HTMLImageElement;
                if (tgt.naturalWidth && tgt.naturalHeight) {
                  const aspect = tgt.naturalWidth / tgt.naturalHeight;
                  setVideoAspect((prev) => (prev !== aspect ? aspect : prev));
                }
                setStreamError(false);
              }}
              onError={() => {
                setStreamError(true);
                if (retryTimeoutRef.current) clearTimeout(retryTimeoutRef.current);
                retryTimeoutRef.current = setTimeout(() => {
                  setStreamCacheBuster(Date.now());
                }, 2000);
              }}
            />
          </div>
        </div>
      )}

      {/* Top Stream Toolbar */}
      <TopToolbar
        isStreaming={isStreaming}
        isFullscreen={isFullscreen}
        onToggleFullscreen={toggleFullscreen}
        isRecording={isRecording}
        recordingDuration={recordingDuration}
        onSnapshot={onSnapshot || handleSnapshot}
        fps={fps || cameraConfig?.targetFps || 30}
      />

      {/* Zoom Controls */}
      {isStreaming && (
        <ZoomControls
          zoom={zoom}
          onZoomIn={zoomIn}
          onZoomOut={zoomOut}
          onResetZoom={resetZoom}
          onSetZoom={setZoomLevel}
          className="absolute right-3 sm:right-4 bottom-3 sm:bottom-4 z-30"
        />
      )}
    </div>
  );
};

export const CameraStreamCanvas = DetectionCanvas;
export default DetectionCanvas;
