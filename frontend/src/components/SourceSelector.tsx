import React, { useState } from 'react';
import { Camera, Play, Square, Loader2, Disc, Video, CameraIcon, Settings } from 'lucide-react';

const formatTime = (totalSeconds: number = 0) => {
  const mins = Math.floor(totalSeconds / 60);
  const secs = totalSeconds % 60;
  return `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
};

export interface SourceSelectorProps {
  isStreaming?: boolean;
  isStarting?: boolean;
  isCameraConnected?: boolean;
  isRecording?: boolean;
  isSavingRecording?: boolean;
  recordingDuration?: number;
  cameraStartingState?: 'idle' | 'waking_camera' | 'waiting_frame' | 'ready';
  onStartStream?: () => void | Promise<void>;
  onStopStream?: () => void | Promise<void>;
  onToggleRecording?: () => void | Promise<void>;
  onTakeSnapshot?: () => void | Promise<void>;
  onOpenSettings?: () => void;

  // Compatibility props (optional)
  sourceType?: string;
  onSourceChange?: (type: any) => void;
  hasActiveVideo?: boolean;
  customVideoName?: string;
}

export const SourceSelector: React.FC<SourceSelectorProps> = ({
  isStreaming = false,
  isStarting = false,
  isCameraConnected = false,
  isRecording = false,
  isSavingRecording = false,
  recordingDuration = 0,
  cameraStartingState = 'ready',
  onStartStream,
  onStopStream,
  onToggleRecording,
  onTakeSnapshot,
  onOpenSettings,
}) => {
  const [isStreamBusy, setIsStreamBusy] = useState(false);
  const [isSnapshotting, setIsSnapshotting] = useState(false);

  const handleToggleStream = async () => {
    if (isStreamBusy) return;
    setIsStreamBusy(true);
    try {
      if (isStreaming) {
        await onStopStream?.();
      } else {
        await onStartStream?.();
      }
    } finally {
      setTimeout(() => setIsStreamBusy(false), 500);
    }
  };

  const handleSnapshot = async () => {
    if (!isStreaming || isSnapshotting) return;
    setIsSnapshotting(true);
    try {
      await onTakeSnapshot?.();
    } finally {
      setTimeout(() => setIsSnapshotting(false), 600);
    }
  };

  const isWarming = cameraStartingState === 'waking_camera' || cameraStartingState === 'waiting_frame' || isStarting;

  return (
    <div className="w-full flex-shrink-0">
      <div className="flex flex-row items-center justify-between gap-2 sm:gap-4 p-2 sm:p-3 rounded-2xl bg-[var(--bg-card)] border border-[var(--border-color)] shadow-sm">
        
        {/* Left: Device Status Indicator */}
        <div className="flex items-center gap-2 sm:gap-3 px-3 py-1.5 rounded-xl bg-[var(--bg-card-subtle)] border border-[var(--border-color)]">
          <div className="flex items-center gap-2">
            <span
              className={`w-2.5 h-2.5 rounded-full ${
                isStreaming
                  ? 'bg-emerald-500 animate-pulse shadow-[0_0_8px_rgba(16,185,129,0.8)]'
                  : isCameraConnected
                  ? 'bg-sky-500'
                  : 'bg-rose-500'
              }`}
            />
            <span className="text-xs font-bold text-[var(--text-primary)] tracking-wide flex items-center gap-1.5">
              <Camera className="w-3.5 h-3.5 text-[var(--accent-pond)]" />
              <span>
                {isStreaming
                  ? 'LIVE STREAMING'
                  : isCameraConnected
                  ? 'STANDBY'
                  : 'DISCONNECTED'}
              </span>
            </span>
          </div>
        </div>

        {/* Right: Stream, Record, Snapshot & Settings Controls */}
        <div className="flex items-center gap-2 sm:gap-3 ml-auto">
          
          {/* 1. Stream Start/Stop Button */}
          {isWarming ? (
            <button
              disabled
              className="h-9 flex items-center gap-2 px-4 rounded-xl bg-amber-600/80 text-white font-bold text-xs shadow-xs cursor-wait opacity-90 transition-all shrink-0"
            >
              <Loader2 className="w-4 h-4 animate-spin" />
              <span>{cameraStartingState === 'waking_camera' ? 'WAKING CAMERA...' : 'STARTING STREAM...'}</span>
            </button>
          ) : isStreaming ? (
            <button
              disabled={isStreamBusy}
              onClick={handleToggleStream}
              title="Stop live camera stream"
              className="h-9 flex items-center gap-2 px-4 rounded-xl bg-slate-700 hover:bg-slate-600 text-white font-bold text-xs shadow-xs active:scale-95 cursor-pointer transition-all shrink-0"
            >
              {isStreamBusy ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
              ) : (
                <Square className="w-3.5 h-3.5 fill-current" />
              )}
              <span>STOP STREAM</span>
            </button>
          ) : (
            <button
              disabled={!isCameraConnected || isStreamBusy}
              onClick={handleToggleStream}
              title={
                !isCameraConnected
                  ? 'Camera not connected — connect an OAK camera to start stream'
                  : 'Start live camera stream'
              }
              className={`h-9 flex items-center gap-2 px-4 sm:px-5 rounded-xl font-bold text-xs shadow-xs transition-all shrink-0 ${
                !isCameraConnected || isStreamBusy
                  ? 'bg-sky-950/40 text-sky-600/40 border border-sky-900/30 cursor-not-allowed opacity-50'
                  : 'bg-sky-600 hover:bg-sky-500 text-white active:scale-95 cursor-pointer shadow-sky-600/20 shadow-md'
              }`}
            >
              {isStreamBusy ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
              ) : (
                <Play className="w-3.5 h-3.5 fill-current" />
              )}
              <span>START STREAM</span>
            </button>
          )}

          {/* 2. Recording Button */}
          <button
            disabled={isSavingRecording || !isCameraConnected}
            onClick={() => onToggleRecording?.()}
            title={
              !isCameraConnected
                ? 'Camera not connected'
                : isSavingRecording
                ? 'Saving recording... please wait'
                : isRecording
                ? 'Stop recording and save file'
                : 'Start recording camera stream to file'
            }
            className={`h-9 flex items-center gap-2 px-3 sm:px-4 rounded-xl font-bold text-xs shadow-xs transition-all shrink-0 ${
              !isCameraConnected
                ? 'bg-rose-500/5 border border-rose-500/20 text-rose-500/40 cursor-not-allowed opacity-40'
                : isSavingRecording
                ? 'bg-rose-700/80 text-white cursor-wait opacity-80'
                : isRecording
                ? 'bg-rose-600 hover:bg-rose-500 text-white animate-pulse ring-2 ring-rose-400/50 shadow-md shadow-rose-600/30 cursor-pointer active:scale-95'
                : 'bg-rose-500/15 hover:bg-rose-500/25 border border-rose-500/40 text-rose-500 dark:text-rose-400 hover:text-rose-600 dark:hover:text-white cursor-pointer active:scale-95'
            }`}
          >
            {isSavingRecording ? (
              <>
                <Loader2 className="w-3.5 h-3.5 animate-spin text-white" />
                <span className="whitespace-nowrap uppercase tracking-wider text-[11px]">SAVING...</span>
              </>
            ) : isRecording ? (
              <>
                <Disc className="w-3.5 h-3.5 text-white animate-spin [animation-duration:3s]" />
                <span className="whitespace-nowrap font-black tracking-wider text-white">REC</span>
                <span className="font-mono text-xs font-bold bg-black/40 border border-white/20 px-1.5 py-0.5 rounded-md text-white">
                  {formatTime(recordingDuration)}
                </span>
              </>
            ) : (
              <>
                <span className="w-2 h-2 rounded-full bg-rose-500 shadow-[0_0_6px_rgba(244,63,94,0.8)]" />
                <Video className="w-3.5 h-3.5 text-rose-500 dark:text-rose-400" />
                <span>RECORD</span>
              </>
            )}
          </button>

          {/* 3. Snapshot Button */}
          <button
            disabled={!isStreaming || isSnapshotting}
            onClick={handleSnapshot}
            title={!isStreaming ? 'Start stream to take snapshot' : 'Capture full-resolution snapshot'}
            className={`h-9 flex items-center gap-1.5 px-3 rounded-xl border font-bold text-xs shadow-xs transition-all shrink-0 ${
              !isStreaming || isSnapshotting
                ? 'border-[var(--border-color)] text-[var(--text-muted)] cursor-not-allowed opacity-50'
                : 'bg-[var(--btn-secondary-bg)] hover:bg-[var(--btn-secondary-hover)] border-[var(--btn-secondary-border)] text-[var(--text-primary)] cursor-pointer active:scale-95'
            }`}
          >
            {isSnapshotting ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin text-[var(--accent-pond)]" />
            ) : (
              <CameraIcon className="w-3.5 h-3.5 text-[var(--accent-pond)]" />
            )}
            <span className="hidden sm:inline">SNAPSHOT</span>
          </button>

          {/* 4. Quick Settings Access */}
          {onOpenSettings && (
            <button
              onClick={onOpenSettings}
              title="Camera & System Settings"
              className="h-9 w-9 flex items-center justify-center rounded-xl bg-[var(--btn-secondary-bg)] hover:bg-[var(--btn-secondary-hover)] border border-[var(--btn-secondary-border)] text-[var(--btn-secondary-text)] transition-all cursor-pointer active:scale-95 shrink-0"
            >
              <Settings className="w-4 h-4 text-[var(--accent-pond)]" />
            </button>
          )}

        </div>
      </div>
    </div>
  );
};

export const CameraActionBar = SourceSelector;
