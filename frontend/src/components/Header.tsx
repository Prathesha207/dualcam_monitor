import React, { useState, useEffect, useCallback } from 'react';
import { ThemeMode, CameraConfig } from '../types';
import { 
  Sun, 
  Moon, 
  Leaf, 
  Settings, 
  HelpCircle, 
  Camera,
  Plus,
  Video,
  Power,
} from 'lucide-react';
import { IconButton } from './ui';
import { getApiBaseUrl } from '../lib/api';

interface HeaderProps {
  theme: ThemeMode;
  onThemeChange: (theme: ThemeMode) => void;
  cameraConfig?: CameraConfig;
  cameras?: CameraConfig[];
  onToggleEnableCamera?: (id: number, currentEnabled: boolean) => void;
  onOpenSettings: () => void;
  onOpenHelp: () => void;
  fps?: number;
  onExitToLanding?: () => void;
  onAddCamera?: () => void;
  canRecordBoth?: boolean;
  isRecordingBoth?: boolean;
  onToggleRecordBoth?: () => void;
  activeCameraCount?: number;
}

export const Header: React.FC<HeaderProps> = ({
  theme,
  onThemeChange,
  cameraConfig,
  cameras = [],
  onToggleEnableCamera,
  onOpenSettings,
  onOpenHelp,
  onExitToLanding,
  onAddCamera,
  canRecordBoth = false,
  isRecordingBoth = false,
  onToggleRecordBoth,
  activeCameraCount = 0,
}) => {
  const [backendConnected, setBackendConnected] = useState<boolean>(false);

  // Live Backend Health Ping
  const checkBackendHealth = useCallback(async () => {
    try {
      const baseUrl = getApiBaseUrl();
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), 2500);
      const res = await fetch(`${baseUrl}/health`, {
        method: 'GET',
        cache: 'no-store',
        signal: controller.signal,
      });
      clearTimeout(timer);
      setBackendConnected(res.ok || res.status === 503);
    } catch {
      setBackendConnected(false);
    }
  }, []);

  useEffect(() => {
    checkBackendHealth();
    const interval = setInterval(checkBackendHealth, 4000);
    return () => clearInterval(interval);
  }, [checkBackendHealth]);

  const cycleTheme = () => {
    if (theme === 'pond-light') onThemeChange('pond-dark');
    else if (theme === 'pond-dark') onThemeChange('nature');
    else onThemeChange('pond-light');
  };

  const getThemeIcon = () => {
    if (theme === 'pond-light') return <Sun className="w-3.5 h-3.5 text-[var(--accent-tube)]" />;
    if (theme === 'pond-dark') return <Moon className="w-3.5 h-3.5 text-[var(--accent-pond)]" />;
    return <Leaf className="w-3.5 h-3.5 text-[var(--accent-pond)]" />;
  };

  return (
    <header className="sticky top-0 z-40 w-full bg-[var(--bg-card)] border-b border-[var(--border-color)] text-[var(--text-primary)] shadow-xs select-none">
      <div className="w-full max-w-[1720px] 2xl:max-w-[1920px] mx-auto px-3 sm:px-5 lg:px-6 py-2 sm:py-2.5 flex items-center justify-between gap-2 sm:gap-3">
        
        {/* 1. Left: Brand Title with PRO badge */}
        <div 
          onClick={() => {
            if (onExitToLanding) {
              onExitToLanding();
            }
          }}
          className={`flex items-center gap-2 sm:gap-2.5 shrink-0 min-w-0 ${onExitToLanding ? 'cursor-pointer hover:opacity-85 transition-opacity' : ''}`}
          title={onExitToLanding ? 'Return to Landing Screen' : undefined}
        >
          <div className="relative flex items-center justify-center w-7 sm:w-8 h-7 sm:h-8 rounded-xl bg-[var(--accent-pond-subtle)] text-[var(--accent-pond)] border border-[var(--border-color)] shrink-0">
            <Camera className="w-4 h-4 sm:w-4.5 sm:h-4.5" />
            <span className="absolute -bottom-0.5 -right-0.5 w-2 h-2 bg-[var(--accent-pond)] rounded-full border-2 border-[var(--bg-card)]" />
          </div>

          <div className="flex flex-col justify-center min-w-0">
            <div className="flex items-center gap-1.5">
              <h1 className="font-bold text-xs sm:text-sm md:text-base text-[var(--text-primary)] tracking-tight whitespace-nowrap leading-none">
                Vision Monitor
              </h1>
              <span className="inline-flex items-center px-1.5 py-0.5 rounded-full text-[9px] sm:text-[9.5px] font-bold tracking-wider bg-[var(--accent-pond-subtle)] text-[var(--accent-pond)] border border-[var(--border-color)] uppercase">
                DUAL CAM
              </span>
            </div>
            <p className="text-[10px] sm:text-[11px] text-[var(--text-secondary)] font-medium whitespace-nowrap leading-tight mt-0.5">
              {activeCameraCount > 0 ? `${activeCameraCount} Camera${activeCameraCount > 1 ? 's' : ''} Connected` : 'Hardware Standby'} • Live Controls &amp; Recording
            </p>
          </div>
        </div>

        {/* 2. Right: Action Buttons & Utilities */}
        <div className="flex items-center gap-1.5 sm:gap-2.5 shrink-0">
          
          {/* Quick Re-enable Pill for any disabled cameras so they don't occupy canvas space but are easily restored */}
          {cameras.filter((c) => c.is_enabled === false).map((c) => (
            <button
              key={c.id}
              onClick={() => c.id && onToggleEnableCamera && onToggleEnableCamera(c.id, false)}
              title={`Hardware power is off for ${c.sourceName || `Camera ${c.id}`}. Click to power on and restore to view.`}
              className="inline-flex items-center gap-1.5 h-8 px-2.5 rounded-xl bg-amber-500/10 hover:bg-amber-500/20 text-amber-600 dark:text-amber-400 border border-amber-500/30 text-xs font-bold transition-all cursor-pointer shadow-xs active:scale-95"
            >
              <Power className="w-3 h-3 stroke-[2.5]" />
              <span className="truncate max-w-[130px]">Power On {c.sourceName || `Cam ${c.id}`}</span>
            </button>
          ))}

          {/* Conditional Record Both: ONLY appears when both cameras are connected */}
          {canRecordBoth && onToggleRecordBoth && (
            <button
              onClick={onToggleRecordBoth}
              title={isRecordingBoth ? 'Stop recording both cameras' : 'Start synchronized recording on both cameras'}
              className={`inline-flex items-center gap-2 h-8 px-3 rounded-xl border text-xs font-bold transition-all cursor-pointer shadow-xs active:scale-95 ${
                isRecordingBoth
                  ? 'bg-[var(--status-anomaly-bg)] text-[var(--status-anomaly-text)] border-[var(--status-anomaly-border)] animate-pulse'
                  : 'bg-[var(--btn-secondary-bg)] text-[var(--btn-secondary-text)] border-[var(--btn-secondary-border)] hover:bg-[var(--btn-secondary-hover)]'
              }`}
            >
              <span className={`w-2.5 h-2.5 rounded-full ${isRecordingBoth ? 'bg-[var(--status-anomaly-text)] animate-ping' : 'bg-red-500'}`} />
              <span>{isRecordingBoth ? 'Stop Both' : 'Record Both'}</span>
            </button>
          )}

          {/* Add Camera Button */}
          {onAddCamera && (
            <button
              onClick={onAddCamera}
              title="Add a new USB or IP/PoE camera"
              className="inline-flex items-center gap-1.5 h-8 px-3 rounded-xl bg-[var(--btn-primary-bg)] text-[var(--btn-primary-text)] font-semibold text-xs shadow-xs hover:opacity-90 active:scale-95 transition-all cursor-pointer whitespace-nowrap"
            >
              <Plus className="w-3.5 h-3.5 stroke-[2.5]" />
              <span>Add Camera</span>
            </button>
          )}

          {/* Backend Status indicator */}
          <div
            title={`Backend: ${backendConnected ? 'Connected' : 'Offline'}`}
            className="hidden sm:inline-flex items-center gap-1.5 h-8 px-2.5 rounded-xl bg-[var(--btn-secondary-bg)] border border-[var(--btn-secondary-border)] text-xs text-[var(--text-secondary)]"
          >
            <span className={`w-2 h-2 rounded-full shrink-0 ${backendConnected ? 'bg-[var(--status-normal-text)]' : 'bg-[var(--status-anomaly-text)]'}`} />
            <span className="font-medium text-[11px]">{backendConnected ? 'Online' : 'Offline'}</span>
          </div>

          {/* Theme Switcher Button */}
          <IconButton
            onClick={cycleTheme}
            aria-label="Toggle Theme"
            icon={getThemeIcon()}
            size="md"
          />

          {/* Help Guide Button */}
          <IconButton
            onClick={onOpenHelp}
            aria-label="User Guide"
            icon={<HelpCircle className="w-3.5 h-3.5 text-[var(--text-secondary)]" />}
            size="md"
          />
        </div>

      </div>
    </header>
  );
};
