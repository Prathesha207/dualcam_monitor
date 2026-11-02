import React from 'react';
import { Camera, Play } from 'lucide-react';

interface CameraStandbyCardProps {
  onStartStream?: () => void;
  onCanvasClick?: (e: React.MouseEvent<HTMLDivElement>) => void;
}

export const CameraStandbyCard: React.FC<CameraStandbyCardProps> = ({
  onStartStream,
  onCanvasClick,
}) => {
  return (
    <div
      onClick={onCanvasClick}
      className="absolute inset-0 w-full h-full flex flex-col items-center justify-center text-center p-6 rounded-3xl z-10 select-none"
      style={{ backgroundColor: 'var(--bg-card)' }}
    >
      <div className="text-[var(--accent-pond)] mb-2 sm:mb-3 shrink-0">
        <Camera className="w-10 h-10 sm:w-12 sm:h-12 lg:w-14 lg:h-14 stroke-[1.75]" />
      </div>

      <div className="inline-flex items-center gap-1.5 px-2.5 sm:px-3.5 py-1 rounded-lg bg-[var(--status-normal-bg)] border border-[var(--status-normal-border)] text-[var(--status-normal-text)] text-[10px] sm:text-xs font-mono font-semibold mb-2.5 shadow-xs">
        <span className="w-1.5 h-1.5 rounded-full bg-[var(--status-normal-text)] animate-pulse" />
        OAK-D CAMERA CONNECTED
      </div>

      <h3 className="text-lg sm:text-xl lg:text-2xl font-bold text-[var(--text-primary)] mb-1 sm:mb-2 shrink-0">
        Camera Feed in Standby
      </h3>
      <p className="text-xs sm:text-sm lg:text-base text-[var(--text-secondary)] max-w-md mb-5 leading-relaxed font-medium">
        Hardware connection is active. Click below to start the live camera stream.
      </p>

      <div className="flex flex-wrap items-center justify-center gap-2.5">
        {onStartStream && (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onStartStream();
            }}
            title="Start live camera stream"
            className="flex items-center gap-1.5 px-5 py-2.5 rounded-xl bg-sky-600 hover:bg-sky-500 text-white font-bold text-xs sm:text-sm shadow-xs transition-all cursor-pointer active:scale-95"
          >
            <Play className="w-4 h-4 fill-current" />
            <span>Start Live Stream</span>
          </button>
        )}
      </div>
    </div>
  );
};
