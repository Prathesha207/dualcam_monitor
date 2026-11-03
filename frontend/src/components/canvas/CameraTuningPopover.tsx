import React, { useState, useEffect, useRef, useCallback } from 'react';
import { SlidersHorizontal, RotateCcw, Focus, Sun, Zap, CheckCircle2, Save, X, Loader2, Minus, ChevronUp } from 'lucide-react';
import type { CameraConfig } from '../../types';
import { cameraService } from '../service/cameraService';

interface CameraTuningPopoverProps {
  cameraId: number;
  cameraIndex: number;
  cameraName: string;
  config: CameraConfig;
  isLive?: boolean;
  onClose: () => void;
  onUpdateConfig?: (partial: Partial<CameraConfig>) => void;
}

export const CameraTuningPopover: React.FC<CameraTuningPopoverProps> = ({
  cameraId,
  cameraIndex,
  cameraName,
  config,
  isLive = true,
  onClose,
  onUpdateConfig,
}) => {
  const [exposure, setExposure] = useState<number>(config.exposure ?? 8);
  const [gain, setGain] = useState<number>(config.gain ?? config.iso ?? 400);
  const [focus, setFocus] = useState<number>(config.focus ?? 128);
  const [brightness, setBrightness] = useState<number>(config.brightness ?? 0);
  const [contrast, setContrast] = useState<number>(config.contrast ?? 50);

  const [activePreset, setActivePreset] = useState<string | null>(null);
  const [isMinimized, setIsMinimized] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  // Initial reference values from database for Reset
  const initialRef = useRef({
    exposure: config.exposure ?? 8,
    gain: config.gain ?? config.iso ?? 400,
    focus: config.focus ?? 128,
    brightness: config.brightness ?? 0,
    contrast: config.contrast ?? 50,
  });

  // Network queue & throttling refs
  const inFlightRef = useRef(false);
  const pendingUpdateRef = useRef<any>(null);
  const throttleTimerRef = useRef<any>(null);
  const lastSentTimeRef = useRef<number>(0);

  // Sync internal state if config changes externally (e.g. loaded from DB)
  useEffect(() => {
    if (!inFlightRef.current && !pendingUpdateRef.current) {
      if (typeof config.exposure === 'number') setExposure(config.exposure);
      if (typeof config.gain === 'number') setGain(config.gain);
      if (typeof config.focus === 'number') setFocus(config.focus);
      if (typeof config.brightness === 'number') setBrightness(config.brightness);
      if (typeof config.contrast === 'number') setContrast(config.contrast);
    }
  }, [config.exposure, config.gain, config.focus, config.brightness, config.contrast]);

  // Actual network dispatch
  const dispatchToBackend = useCallback(
    async (payload: any) => {
      if (inFlightRef.current) {
        pendingUpdateRef.current = payload;
        return;
      }
      inFlightRef.current = true;
      lastSentTimeRef.current = Date.now();

      try {
        await cameraService.updateLiveControls(cameraId, payload);
      } catch (err) {
        console.warn(`[CameraTuningPopover] Failed updating Camera ${cameraId}:`, err);
      } finally {
        inFlightRef.current = false;
        if (pendingUpdateRef.current) {
          const next = pendingUpdateRef.current;
          pendingUpdateRef.current = null;
          dispatchToBackend(next);
        }
      }
    },
    [cameraId]
  );

  // Throttled schedule: immediate on first event, paced at ~100ms while dragging
  const scheduleDispatch = useCallback(
    (payload: any) => {
      const now = Date.now();
      const elapsed = now - lastSentTimeRef.current;
      const THROTTLE_MS = 100;

      if (elapsed >= THROTTLE_MS && !inFlightRef.current) {
        if (throttleTimerRef.current) {
          clearTimeout(throttleTimerRef.current);
          throttleTimerRef.current = null;
        }
        dispatchToBackend(payload);
      } else {
        pendingUpdateRef.current = payload;
        if (!throttleTimerRef.current) {
          throttleTimerRef.current = setTimeout(() => {
            throttleTimerRef.current = null;
            if (pendingUpdateRef.current) {
              const next = pendingUpdateRef.current;
              pendingUpdateRef.current = null;
              dispatchToBackend(next);
            }
          }, Math.max(10, THROTTLE_MS - elapsed));
        }
      }
    },
    [dispatchToBackend]
  );

  // Sliders Change Handlers
  const handleGainChange = (val: number) => {
    setGain(val);
    setActivePreset(null);
    onUpdateConfig?.({ gain: val, iso: val, controlMode: 'manual' });
    scheduleDispatch({ control_mode: 'manual', gain: val, exposure, focus, brightness, contrast });
  };

  const handleFocusChange = (val: number) => {
    setFocus(val);
    setActivePreset(null);
    onUpdateConfig?.({ focus: val, controlMode: 'manual' });
    scheduleDispatch({ control_mode: 'manual', gain, exposure, focus: val, brightness, contrast });
  };

  const handleExposureChange = (val: number) => {
    setExposure(val);
    setActivePreset(null);
    onUpdateConfig?.({ exposure: val, controlMode: 'manual' });
    scheduleDispatch({ control_mode: 'manual', gain, exposure: val, focus, brightness, contrast });
  };

  const handleBrightnessChange = (val: number) => {
    setBrightness(val);
    setActivePreset(null);
    onUpdateConfig?.({ brightness: val, controlMode: 'manual' });
    scheduleDispatch({ control_mode: 'manual', gain, exposure, focus, brightness: val, contrast });
  };

  const handleContrastChange = (val: number) => {
    setContrast(val);
    setActivePreset(null);
    onUpdateConfig?.({ contrast: val, controlMode: 'manual' });
    scheduleDispatch({ control_mode: 'manual', gain, exposure, focus, brightness, contrast: val });
  };

  // Presets Handlers
  const handleApplyPreset = (presetName: 'clean' | 'default' | 'night') => {
    setActivePreset(presetName);
    let newGain = gain;
    let newExp = exposure;
    let newFocus = focus;
    let newB = brightness;
    let newC = contrast;

    if (presetName === 'clean') {
      newGain = 100;
      newExp = 18;
      newB = 0;
      newC = 50;
    } else if (presetName === 'default') {
      newGain = 400;
      newExp = 8;
      newB = 0;
      newC = 50;
    } else if (presetName === 'night') {
      newGain = 1200;
      newExp = 33;
      newB = 10;
      newC = 60;
    }

    setGain(newGain);
    setExposure(newExp);
    setFocus(newFocus);
    setBrightness(newB);
    setContrast(newC);

    onUpdateConfig?.({
      gain: newGain,
      iso: newGain,
      exposure: newExp,
      focus: newFocus,
      brightness: newB,
      contrast: newC,
      controlMode: 'manual',
    });

    scheduleDispatch({
      control_mode: 'manual',
      gain: newGain,
      exposure: newExp,
      focus: newFocus,
      brightness: newB,
      contrast: newC,
    });
  };

  // Reset to initial values
  const handleReset = () => {
    setActivePreset(null);
    const { exposure: initExp, gain: initGain, focus: initFocus, brightness: initB, contrast: initC } = initialRef.current;
    setExposure(initExp);
    setGain(initGain);
    setFocus(initFocus);
    setBrightness(initB);
    setContrast(initC);

    onUpdateConfig?.({
      exposure: initExp,
      gain: initGain,
      iso: initGain,
      focus: initFocus,
      brightness: initB,
      contrast: initC,
      controlMode: 'manual',
    });

    scheduleDispatch({
      control_mode: 'manual',
      exposure: initExp,
      gain: initGain,
      focus: initFocus,
      brightness: initB,
      contrast: initC,
    });
  };

  // Save Settings to Database
  const handleSaveSettings = async () => {
    setIsSaving(true);
    setSaveError(null);
    try {
      await cameraService.updateLiveControls(cameraId, {
        control_mode: 'manual',
        exposure,
        gain,
        focus,
        brightness,
        contrast,
        save_to_db: true,
      });

      // Update initialRef so subsequent Reset reverts to these newly saved settings
      initialRef.current = { exposure, gain, focus, brightness, contrast };

      setSaveSuccess(true);
      setTimeout(() => setSaveSuccess(false), 2000);
    } catch (err: any) {
      setSaveError(err?.message || 'Failed to save settings');
      setTimeout(() => setSaveError(null), 3000);
    } finally {
      setIsSaving(false);
    }
  };

  // Helper for slider gradient fill
  const getSliderStyle = (val: number, min: number, max: number) => {
    const pct = Math.max(0, Math.min(100, ((val - min) / (max - min)) * 100));
    return {
      background: `linear-gradient(to right, var(--accent-pond, #06b6d4) 0%, var(--accent-pond, #06b6d4) ${pct}%, var(--border-color, #cbd5e1) ${pct}%, var(--border-color, #cbd5e1) 100%)`,
      accentColor: 'var(--accent-pond, #06b6d4)',
    };
  };

  // Minimized Ultra-Compact Single-Line Bar
  if (isMinimized) {
    return (
      <div
        className="absolute right-2.5 bottom-2.5 z-40 rounded-xl bg-[var(--bg-card)]/90 dark:bg-slate-900/90 backdrop-blur-md border border-[var(--border-color)] dark:border-slate-700 shadow-lg px-2.5 py-1.5 flex items-center gap-2 select-none animate-in fade-in duration-100 text-[var(--text-primary)]"
        onClick={(e) => e.stopPropagation()}
        onMouseDown={(e) => e.stopPropagation()}
        onDoubleClick={(e) => e.stopPropagation()}
      >
        <div
          className="flex items-center gap-1.5 cursor-pointer hover:opacity-80 transition-opacity"
          onClick={() => setIsMinimized(false)}
          title="Click to expand tuning panel"
        >
          <SlidersHorizontal className="w-3.5 h-3.5 text-[var(--accent-pond)] shrink-0" />
          <span className="text-[11px] font-bold">CAM {cameraIndex}</span>
          <span className="text-[10px] font-mono text-[var(--text-secondary)]">
            ISO {gain} • {exposure}ms
          </span>
        </div>
        <button
          type="button"
          onClick={() => setIsMinimized(false)}
          title="Expand tuning controls"
          className="w-5 h-5 rounded hover:bg-[var(--btn-secondary-hover)] flex items-center justify-center text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors cursor-pointer"
        >
          <ChevronUp className="w-3.5 h-3.5" />
        </button>
        <button
          type="button"
          onClick={onClose}
          title="Close tuning"
          className="w-5 h-5 rounded hover:bg-[var(--btn-secondary-hover)] flex items-center justify-center text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors cursor-pointer"
        >
          <X className="w-3 h-3" />
        </button>
      </div>
    );
  }

  return (
    <div
      className="absolute right-2.5 bottom-2.5 z-40 w-[235px] sm:w-[245px] max-w-[calc(100%-20px)] max-h-[calc(100%-20px)] overflow-y-auto rounded-2xl bg-[var(--bg-card)]/95 dark:bg-slate-900/95 backdrop-blur-md border border-[var(--border-color)] dark:border-slate-700 shadow-2xl p-2 flex flex-col gap-1 select-none animate-in fade-in zoom-in-95 duration-150 text-[var(--text-primary)]"
      onClick={(e) => e.stopPropagation()}
      onMouseDown={(e) => e.stopPropagation()}
      onDoubleClick={(e) => e.stopPropagation()}
    >
      {/* 1. Popover Header (Title, CAM badge, Minimize, Close - NO reset here) */}
      <div className="flex items-center justify-between pb-1 border-b border-[var(--border-color)]">
        <div className="flex items-center gap-1.5 min-w-0">
          <SlidersHorizontal className="w-3.5 h-3.5 text-[var(--accent-pond)] shrink-0" />
          <h3 className="font-bold text-xs text-[var(--text-primary)] truncate tracking-tight">
            {cameraName ? `${cameraName} Tuning` : `Camera 0${cameraIndex} Tuning`}
          </h3>
          <span className="px-1 py-0.2 rounded text-[9px] font-mono font-bold bg-[var(--accent-pond-subtle)] text-[var(--accent-pond)] border border-[var(--accent-pond)]/30 shrink-0">
            CAM {cameraIndex}
          </span>
        </div>

        <div className="flex items-center gap-1 shrink-0">
          <button
            type="button"
            onClick={() => setIsMinimized(true)}
            title="Minimize to small bar"
            className="w-5 h-5 rounded hover:bg-[var(--btn-secondary-hover)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] flex items-center justify-center transition-colors cursor-pointer"
          >
            <Minus className="w-3.5 h-3.5" />
          </button>
          <button
            type="button"
            onClick={onClose}
            title="Close tuning popover"
            className="w-5 h-5 rounded hover:bg-[var(--btn-secondary-hover)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] flex items-center justify-center transition-colors cursor-pointer"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {/* 2. Sensor Gain (ISO) */}
      <div className="py-1 px-2 rounded-lg bg-[var(--bg-card-subtle)] border border-[var(--border-color)]">
        <div className="flex items-center justify-between leading-none mb-0.5">
          <div className="flex items-center gap-1 text-[11px] font-bold text-[var(--text-primary)]">
            <Zap className="w-3 h-3 text-amber-500 fill-amber-500/20" />
            <span>Gain</span>
          </div>
          <span className="px-1.5 py-0.2 rounded font-mono text-[9.5px] font-bold bg-amber-500/10 text-amber-600 dark:text-amber-400 border border-amber-500/20 leading-none">
            ISO {gain}
          </span>
        </div>
        <input
          type="range"
          min={100}
          max={1600}
          step={10}
          value={gain}
          onChange={(e) => handleGainChange(parseInt(e.target.value, 10))}
          style={getSliderStyle(gain, 100, 1600)}
          className="w-full h-1 block cursor-pointer m-0 p-0"
        />
      </div>

      {/* 3. Focus Lens */}
      <div className="py-1 px-2 rounded-lg bg-[var(--bg-card-subtle)] border border-[var(--border-color)]">
        <div className="flex items-center justify-between leading-none mb-0.5">
          <div className="flex items-center gap-1 text-[11px] font-bold text-[var(--text-primary)]">
            <Focus className="w-3 h-3 text-[var(--accent-pond)]" />
            <span>Focus</span>
          </div>
          <span className="px-1.5 py-0.2 rounded font-mono text-[9.5px] font-bold bg-[var(--accent-pond-subtle)] text-[var(--accent-pond)] border border-[var(--accent-pond)]/30 leading-none">
            {config.focusAvailable === false ? 'Auto' : focus}
          </span>
        </div>
        <input
          type="range"
          min={0}
          max={255}
          step={1}
          value={focus}
          disabled={config.focusAvailable === false}
          onChange={(e) => handleFocusChange(parseInt(e.target.value, 10))}
          style={getSliderStyle(focus, 0, 255)}
          className="w-full h-1 block cursor-pointer disabled:opacity-40 m-0 p-0"
        />
      </div>

      {/* 4. Exposure Shutter */}
      <div className="py-1 px-2 rounded-lg bg-[var(--bg-card-subtle)] border border-[var(--border-color)]">
        <div className="flex items-center justify-between leading-none mb-0.5">
          <div className="flex items-center gap-1 text-[11px] font-bold text-[var(--text-primary)]">
            <Sun className="w-3 h-3 text-[var(--accent-pond)]" />
            <span>Exposure</span>
          </div>
          <span className="px-1.5 py-0.2 rounded font-mono text-[9.5px] font-bold bg-[var(--accent-pond-subtle)] text-[var(--accent-pond)] border border-[var(--accent-pond)]/30 leading-none">
            {exposure} ms
          </span>
        </div>
        <input
          type="range"
          min={1}
          max={33}
          step={1}
          value={exposure}
          onChange={(e) => handleExposureChange(parseInt(e.target.value, 10))}
          style={getSliderStyle(exposure, 1, 33)}
          className="w-full h-1 block cursor-pointer m-0 p-0"
        />
      </div>

      {/* 5. Tone (Brightness & Contrast side-by-side) */}
      <div className="py-1 px-2 rounded-lg bg-[var(--bg-card-subtle)] border border-[var(--border-color)] grid grid-cols-2 gap-2">
        <div>
          <div className="flex items-center justify-between text-[10px] font-medium text-[var(--text-secondary)] leading-none mb-0.5">
            <span>Brightness</span>
            <span className="font-mono font-bold text-[var(--accent-pond)] text-[9px] leading-none">
              {brightness > 0 ? `+${brightness}` : brightness}
            </span>
          </div>
          <input
            type="range"
            min={-50}
            max={50}
            step={1}
            value={brightness}
            onChange={(e) => handleBrightnessChange(parseInt(e.target.value, 10))}
            style={getSliderStyle(brightness, -50, 50)}
            className="w-full h-1 block cursor-pointer m-0 p-0"
          />
        </div>
        <div>
          <div className="flex items-center justify-between text-[10px] font-medium text-[var(--text-secondary)] leading-none mb-0.5">
            <span>Contrast</span>
            <span className="font-mono font-bold text-[var(--accent-pond)] text-[9px] leading-none">{contrast}</span>
          </div>
          <input
            type="range"
            min={0}
            max={100}
            step={1}
            value={contrast}
            onChange={(e) => handleContrastChange(parseInt(e.target.value, 10))}
            style={getSliderStyle(contrast, 0, 100)}
            className="w-full h-1 block cursor-pointer m-0 p-0"
          />
        </div>
      </div>

      {/* 6. Presets Row */}
      <div className="flex items-center gap-1 pt-0.5">
        <span className="text-[10px] font-bold text-[var(--text-secondary)] shrink-0">Presets:</span>
        <div className="flex items-center gap-1 flex-1">
          <button
            type="button"
            onClick={() => handleApplyPreset('clean')}
            className={`flex-1 py-0.5 px-1 rounded-lg text-[9.5px] font-bold transition-all cursor-pointer ${
              activePreset === 'clean'
                ? 'bg-[var(--accent-pond)] text-white shadow-xs'
                : 'bg-[var(--bg-card-subtle)] hover:bg-[var(--btn-secondary-hover)] text-[var(--text-primary)] border border-[var(--border-color)]'
            }`}
          >
            Clean
          </button>
          <button
            type="button"
            onClick={() => handleApplyPreset('default')}
            className={`flex-1 py-0.5 px-1 rounded-lg text-[9.5px] font-bold transition-all cursor-pointer ${
              activePreset === 'default'
                ? 'bg-[var(--accent-pond)] text-white shadow-xs'
                : 'bg-[var(--bg-card-subtle)] hover:bg-[var(--btn-secondary-hover)] text-[var(--text-primary)] border border-[var(--border-color)]'
            }`}
          >
            Default
          </button>
          <button
            type="button"
            onClick={() => handleApplyPreset('night')}
            className={`flex-1 py-0.5 px-1 rounded-lg text-[9.5px] font-bold transition-all cursor-pointer ${
              activePreset === 'night'
                ? 'bg-[var(--accent-pond)] text-white shadow-xs'
                : 'bg-[var(--bg-card-subtle)] hover:bg-[var(--btn-secondary-hover)] text-[var(--text-primary)] border border-[var(--border-color)]'
            }`}
          >
            Night
          </button>
        </div>
      </div>

      {/* 7. Bottom Action Buttons: [ ↺ Reset ] and [ 💾 Save Settings ] */}
      <div className="flex items-center gap-1.5 pt-1 border-t border-[var(--border-color)]">
        <button
          type="button"
          onClick={handleReset}
          className="h-7 px-2.5 rounded-xl bg-[var(--btn-secondary-bg)] hover:bg-[var(--btn-secondary-hover)] border border-[var(--btn-secondary-border)] text-[var(--btn-secondary-text)] font-bold text-[11px] flex items-center gap-1 transition-colors cursor-pointer active:scale-95 shadow-2xs shrink-0"
        >
          <RotateCcw className="w-3 h-3" />
          <span>Reset</span>
        </button>

        <button
          type="button"
          onClick={handleSaveSettings}
          disabled={isSaving}
          className="flex-1 h-7 rounded-xl bg-[var(--btn-primary-bg)] hover:bg-[var(--btn-primary-hover)] text-[var(--btn-primary-text)] border border-[var(--border-color)] font-bold text-[11px] flex items-center justify-center gap-1 shadow-xs transition-all cursor-pointer disabled:opacity-50 active:scale-95"
        >
          {isSaving ? (
            <>
              <Loader2 className="w-3 h-3 animate-spin" />
              <span>Saving...</span>
            </>
          ) : saveSuccess ? (
            <>
              <CheckCircle2 className="w-3 h-3 text-emerald-300" />
              <span>Saved!</span>
            </>
          ) : (
            <>
              <Save className="w-3 h-3" />
              <span>Save Settings</span>
            </>
          )}
        </button>
      </div>

      {saveError && (
        <p className="text-[9.5px] text-red-500 font-medium text-center">{saveError}</p>
      )}
    </div>
  );
};
