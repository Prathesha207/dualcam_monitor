import React from 'react';
import { Minimize2, Expand, Disc, Camera as CameraIcon, Radio } from 'lucide-react';

const formatRecordingTime = (totalSeconds: number = 0) => {
  const mins = Math.floor(totalSeconds / 60);
  const secs = totalSeconds % 60;
  return `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
};

interface TopToolbarProps {
  isStreaming: boolean;
  isFullscreen: boolean;
  onToggleFullscreen: () => void;
  isRecording?: boolean;
  recordingDuration?: number;
  onSnapshot?: () => void;
  fps?: number;
}

export const TopToolbar: React.FC<TopToolbarProps> = ({
  isStreaming,
  isFullscreen,
  onToggleFullscreen,
  isRecording = false,
  recordingDuration = 0,
  onSnapshot,
  fps = 30,
}) => {
  if (!isStreaming && !isRecording) return null;

  return (
    <div className="absolute top-0 left-0 right-0 p-2 sm:p-3 flex items-center justify-between gap-2 pointer-events-none z-30 max-w-full overflow-hidden select-none">
      {/* Top-Left: Live Stream Status */}
      <div className="pointer-events-auto flex items-center gap-2 shrink-0">
        <div className="flex items-center h-8 px-3 rounded-xl bg-[var(--bg-card)]/95 backdrop-blur-md border border-[var(--border-color)] shadow-xs select-none">
          {isStreaming ? (
            <div className="flex items-center gap-2 text-emerald-500 font-bold text-xs sm:text-sm">
              <span className="w-2.5 h-2.5 rounded-full bg-emerald-500 animate-pulse shadow-[0_0_8px_rgba(16,185,129,0.8)]" />
              <span>LIVE</span>
              {fps > 0 && (
                <span className="text-[11px] font-mono text-[var(--text-secondary)] font-normal border-l border-[var(--border-color)] pl-2 ml-0.5">
                  {Math.round(fps)} FPS
                </span>
              )}
            </div>
          ) : (
            <div className="flex items-center gap-2 text-amber-500 font-bold text-xs sm:text-sm">
              <Radio className="w-3.5 h-3.5 text-amber-500" />
              <span>STANDBY</span>
            </div>
          )}
        </div>
      </div>

      {/* Top-Center: Active Recording Indicator */}
      {isRecording && (
        <div className="pointer-events-auto flex items-center gap-2 h-8 px-3.5 rounded-xl bg-red-950/90 border border-red-500/50 backdrop-blur-md shadow-lg shadow-red-500/20 animate-pulse">
          <Disc className="w-4 h-4 text-red-400 animate-spin" />
          <span className="text-xs font-bold font-mono tracking-wider text-red-200">
            REC {formatRecordingTime(recordingDuration)}
          </span>
        </div>
      )}

      {/* Top-Right: Snapshot and Fullscreen */}
      <div className="pointer-events-auto flex items-center gap-1.5 shrink-0">
        {onSnapshot && (
          <button
            onClick={onSnapshot}
            title="Take Snapshot"
            className="flex items-center justify-center w-8 h-8 rounded-xl bg-[var(--bg-card)]/95 backdrop-blur-md border border-[var(--border-color)] text-[var(--text-primary)] hover:bg-[var(--btn-secondary-hover)] shadow-xs transition-colors cursor-pointer"
          >
            <CameraIcon className="w-4 h-4" />
          </button>
        )}

        <button
          onClick={onToggleFullscreen}
          title={isFullscreen ? 'Exit Fullscreen' : 'Enter Fullscreen'}
          className="flex items-center justify-center w-8 h-8 rounded-xl bg-[var(--bg-card)]/95 backdrop-blur-md border border-[var(--border-color)] text-[var(--text-primary)] hover:bg-[var(--btn-secondary-hover)] shadow-xs transition-colors cursor-pointer"
        >
          {isFullscreen ? <Minimize2 className="w-4 h-4" /> : <Expand className="w-4 h-4" />}
        </button>
      </div>
    </div>
  );
};
