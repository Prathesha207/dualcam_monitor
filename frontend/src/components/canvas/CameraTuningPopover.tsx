import React, { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { Settings, SlidersHorizontal, RotateCcw, Focus, Sun, Zap, CheckCircle2, Save, X, Loader2, Minus, ChevronUp, AlertTriangle, Info } from 'lucide-react';
import type { CameraConfig } from '../../types';
import { cameraService } from '../service/cameraService';

interface CameraTuningPopoverProps {
  cameraId: number;
  cameraIndex: number;
  cameraName: string;
  config: CameraConfig;
  isLive?: boolean;
  isRecording?: boolean;
  onClose: () => void;
  onUpdateConfig?: (partial: Partial<CameraConfig>) => void;
}

// ── Log-Scale Conversion Helpers ──
function valToLogPos(val: number, min: number, max: number): number {
  if (!Number.isFinite(min) || !Number.isFinite(max) || min <= 0 || max <= min) {
    return 0;
  }
  const safeVal = Math.max(min, Math.min(max, val));
  const logMin = Math.log(min);
  const logMax = Math.log(max);
  return Math.round(((Math.log(safeVal) - logMin) / (logMax - logMin)) * 1000);
}

function logPosToVal(pos: number, min: number, max: number, precision: number = 0): number {
  if (!Number.isFinite(min) || !Number.isFinite(max) || min <= 0 || max <= min) {
    return min;
  }
  const p = Math.max(0, Math.min(1000, pos)) / 1000;
  const logMin = Math.log(min);
  const logMax = Math.log(max);
  const val = Math.exp(logMin + p * (logMax - logMin));
  if (precision === 0) return Math.round(val);
  const factor = Math.pow(10, precision);
  return Math.round(val * factor) / factor;
}

export const CameraTuningPopover: React.FC<CameraTuningPopoverProps> = ({
  cameraId,
  cameraIndex,
  cameraName,
  config,
  isLive = true,
  isRecording = false,
  onClose,
  onUpdateConfig,
}) => {
  const activeFps = config.targetFps || config.fps || 30;

  // ── Dynamic Limits State ──
  const [limitsData, setLimitsData] = useState<any>(null);

  useEffect(() => {
    let isMounted = true;
    cameraService.getCameraLimits(cameraId).then((data) => {
      if (isMounted && data) {
        setLimitsData(data);
      }
    });
    return () => {
      isMounted = false;
    };
  }, [cameraId, activeFps]);

  // Dynamic limits fallbacks (with sanity guard against inverted cached ranges)
  const rawGainMin = limitsData?.controls?.gain?.hardware_min;
  const rawGainMax = limitsData?.controls?.gain?.hardware_max;
  const hasValidGain = Number.isFinite(rawGainMin) && Number.isFinite(rawGainMax) && rawGainMax > rawGainMin;
  const gainHwMin = hasValidGain ? rawGainMin : 65;
  const gainHwMax = hasValidGain ? rawGainMax : 16585;
  const gainRecMin = limitsData?.controls?.gain?.recommended_min ?? 100;
  const gainRecMax = limitsData?.controls?.gain?.recommended_max ?? 6400;

  const rawExpMinUs = limitsData?.controls?.exposure?.hardware_min;
  const rawExpMaxUs = limitsData?.controls?.exposure?.hardware_max;
  const hasValidExp = Number.isFinite(rawExpMinUs) && Number.isFinite(rawExpMaxUs) && rawExpMinUs > 0 && rawExpMaxUs > rawExpMinUs;
  const expHwMinMs = hasValidExp ? rawExpMinUs / 1000.0 : 0.086;
  const expHwMaxMs = hasValidExp ? rawExpMaxUs / 1000.0 : 1000.0;
  const expRecMinMs = limitsData?.controls?.exposure ? limitsData.controls.exposure.recommended_min / 1000.0 : 0.1;
  const expRecMaxMs = limitsData?.controls?.exposure ? limitsData.controls.exposure.recommended_max / 1000.0 : Math.floor(950 / activeFps);
  const framePeriodMs = limitsData?.controls?.exposure?.frame_period_us
    ? limitsData.controls.exposure.frame_period_us / 1000.0
    : 1000.0 / activeFps;

  const focusMin = limitsData?.controls?.focus?.hardware_min ?? 0;
  const focusMax = limitsData?.controls?.focus?.hardware_max ?? 255;

  const contrastMin = limitsData?.controls?.contrast?.hardware_min ?? -10;
  const contrastMax = limitsData?.controls?.contrast?.hardware_max ?? 10;
  const contrastRecMin = limitsData?.controls?.contrast?.recommended_min ?? -5;
  const contrastRecMax = limitsData?.controls?.contrast?.recommended_max ?? 8;

  const brightnessMin = limitsData?.controls?.brightness?.min ?? -50;
  const brightnessMax = limitsData?.controls?.brightness?.max ?? 50;
  const brightnessRecMin = limitsData?.controls?.brightness?.recommended_min ?? -20;
  const brightnessRecMax = limitsData?.controls?.brightness?.recommended_max ?? 20;

  const getWarningMsg = (ctrl: string, op: string, fallback: string): string => {
    const rule = limitsData?.controls?.[ctrl]?.warnings?.find((w: any) => w.op === op);
    return rule?.message || fallback;
  };

  // ── Active Control Values ──
  const [exposure, setExposure] = useState<number>(config.exposure ?? 8);
  const [gain, setGain] = useState<number>(config.gain ?? config.iso ?? 400);
  const [focus, setFocus] = useState<number>(config.focus && config.focus > 0 ? config.focus : 128);
  const [brightness, setBrightness] = useState<number>(config.brightness ?? 0);
  const [contrast, setContrast] = useState<number>(config.contrast ?? 0);

  const [activePreset, setActivePreset] = useState<string | null>(null);
  const [isMinimized, setIsMinimized] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  // Squelched/Debounced Telemetry
  const [debouncedTelemetry, setDebouncedTelemetry] = useState<any>(null);
  const telemetrySettleTimerRef = useRef<any>(null);

  useEffect(() => {
    if (telemetrySettleTimerRef.current) {
      clearTimeout(telemetrySettleTimerRef.current);
    }
    telemetrySettleTimerRef.current = setTimeout(() => {
      setDebouncedTelemetry(config.telemetry);
    }, 300);
    return () => {
      if (telemetrySettleTimerRef.current) clearTimeout(telemetrySettleTimerRef.current);
    };
  }, [config.telemetry, gain, exposure]);

  // Initial reference values for Reset
  const initialRef = useRef({
    exposure: config.exposure ?? 8,
    gain: config.gain ?? config.iso ?? 400,
    focus: config.focus && config.focus > 0 ? config.focus : 128,
    brightness: config.brightness ?? 0,
    contrast: config.contrast ?? 0,
  });

  // Network queue & throttling refs
  const inFlightRef = useRef(false);
  const pendingUpdateRef = useRef<any>(null);
  const throttleTimerRef = useRef<any>(null);
  const lastSentTimeRef = useRef<number>(0);

  // Sync internal state if config changes externally
  useEffect(() => {
    if (!inFlightRef.current && !pendingUpdateRef.current) {
      if (typeof config.exposure === 'number') setExposure(config.exposure);
      if (typeof config.gain === 'number') setGain(config.gain);
      if (typeof config.focus === 'number' && config.focus > 0) setFocus(config.focus);
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
            if (pendingUpdateRef.current && !inFlightRef.current) {
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

  // ── Slider Handlers ──
  const handleGainChange = (val: number) => {
    if (isRecording) return;
    setGain(val);
    setActivePreset(null);
    onUpdateConfig?.({ gain: val, iso: val, controlMode: 'manual' });
    scheduleDispatch({ control_mode: 'manual', gain: val, exposure, focus, brightness, contrast });
  };

  const handleFocusChange = (val: number) => {
    if (isRecording) return;
    setFocus(val);
    setActivePreset(null);
    onUpdateConfig?.({ focus: val, controlMode: 'manual' });
    scheduleDispatch({ control_mode: 'manual', gain, exposure, focus: val, brightness, contrast });
  };

  const handleExposureChange = (val: number) => {
    if (isRecording) return;
    setExposure(val);
    setActivePreset(null);
    onUpdateConfig?.({ exposure: val, controlMode: 'manual' });
    scheduleDispatch({ control_mode: 'manual', gain, exposure: val, focus, brightness, contrast });
  };

  const handleBrightnessChange = (val: number) => {
    if (isRecording) return;
    setBrightness(val);
    setActivePreset(null);
    onUpdateConfig?.({ brightness: val, controlMode: 'manual' });
    scheduleDispatch({ control_mode: 'manual', gain, exposure, focus, brightness: val, contrast });
  };

  const handleContrastChange = (val: number) => {
    if (isRecording) return;
    setContrast(val);
    setActivePreset(null);
    onUpdateConfig?.({ contrast: val, controlMode: 'manual' });
    scheduleDispatch({ control_mode: 'manual', gain, exposure, focus, brightness, contrast: val });
  };

  // ── Presets ──
  const handleApplyPreset = (presetName: 'clean' | 'default' | 'night') => {
    if (isRecording) return;
    setActivePreset(presetName);
    let newGain = gain;
    let newExp = exposure;
    let newFocus = focus;
    let newB = brightness;
    let newC = contrast;

    if (presetName === 'clean') {
      newGain = 100;
      newExp = Math.min(18, expRecMaxMs);
      newB = 0;
      newC = 0;
    } else if (presetName === 'default') {
      newGain = 400;
      newExp = Math.min(8, expRecMaxMs);
      newFocus = 128;
      newB = 0;
      newC = 0;
    } else if (presetName === 'night') {
      newGain = 1600;
      newExp = Math.min(33, framePeriodMs);
      newB = 0;
      newC = 2;
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

  // ── Reset ──
  const handleReset = () => {
    if (isRecording) return;
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

  // ── Save to DB ──
  const handleSaveSettings = async () => {
    if (isRecording) return;
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

      if (cameraId) {
        await cameraService.updateCamera(cameraId, {
          exposure,
          gain,
          focus,
          brightness,
          contrast,
          control_mode: 'manual',
        }).catch(() => {});
      }

      onUpdateConfig?.({
        exposure,
        gain,
        iso: gain,
        focus,
        focusAvailable: true,
        brightness,
        contrast,
        controlMode: 'manual',
      });

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

  // Slider styles with optional green recommended zone
  const getLinearSliderStyle = (val: number, min: number, max: number, recMin?: number, recMax?: number) => {
    const pct = Math.max(0, Math.min(100, ((val - min) / (max - min)) * 100));
    return {
      background: `linear-gradient(to right, var(--accent-pond, #06b6d4) 0%, var(--accent-pond, #06b6d4) ${pct}%, var(--border-color, #cbd5e1) ${pct}%, var(--border-color, #cbd5e1) 100%)`,
      accentColor: 'var(--accent-pond, #06b6d4)',
    };
  };

  const getLogSliderStyle = (pos: number) => {
    const pct = Math.max(0, Math.min(100, pos / 10));
    return {
      background: `linear-gradient(to right, var(--accent-pond, #06b6d4) 0%, var(--accent-pond, #06b6d4) ${pct}%, var(--border-color, #cbd5e1) ${pct}%, var(--border-color, #cbd5e1) 100%)`,
      accentColor: 'var(--accent-pond, #06b6d4)',
    };
  };

  // Telemetry matching
  const appliedIso = debouncedTelemetry?.iso;
  const appliedExpMs = debouncedTelemetry?.exposure_ms;
  const hasIsoTelemetryDiff = appliedIso && appliedIso !== gain;
  const hasExpTelemetryDiff = appliedExpMs && Math.abs(appliedExpMs - exposure) / Math.max(0.1, exposure) > 0.02;

  // ── Minimized Ultra-Compact Single-Line Bar ──
  if (isMinimized) {
    return (
      <div
        className="absolute right-2.5 bottom-2.5 z-40 rounded-xl bg-[var(--bg-card)]/95 backdrop-blur-md border border-[var(--border-color)] shadow-lg px-2.5 py-1.5 flex items-center gap-2 select-none animate-in fade-in duration-100 text-[var(--text-primary)]"
        onClick={(e) => e.stopPropagation()}
        onMouseDown={(e) => e.stopPropagation()}
        onDoubleClick={(e) => e.stopPropagation()}
      >
        <div
          className="flex items-center gap-1.5 cursor-pointer hover:opacity-80 transition-opacity"
          onClick={() => setIsMinimized(false)}
          title="Click to expand tuning panel"
        >
          <Settings className="w-3.5 h-3.5 text-[var(--accent-pond)] shrink-0" />
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
          <X className="w-3.5 h-3.5" />
        </button>
      </div>
    );
  }

  // Exposure Warning Calculation
  const isExpAboveFramePeriod = exposure > framePeriodMs;
  const isExpNearLimit = exposure > expRecMaxMs && exposure <= framePeriodMs;
  const calcFps = isExpAboveFramePeriod ? Math.min(activeFps, Math.floor(1000 / exposure)) : activeFps;

  return (
    <div
      className="absolute right-2.5 bottom-2.5 z-40 w-[245px] sm:w-[255px] max-w-[calc(100%-20px)] max-h-[calc(100%-20px)] overflow-y-auto rounded-2xl bg-[var(--bg-card)]/95 backdrop-blur-md border border-[var(--border-color)] shadow-2xl p-2 flex flex-col gap-1 select-none animate-in fade-in zoom-in-95 duration-150 text-[var(--text-primary)]"
      onClick={(e) => e.stopPropagation()}
      onMouseDown={(e) => e.stopPropagation()}
      onDoubleClick={(e) => e.stopPropagation()}
    >
      {/* 1. Popover Header */}
      <div className="flex items-center justify-between pb-1 border-b border-[var(--border-color)]">
        <div className="flex items-center gap-1.5 min-w-0">
          <Settings className="w-3.5 h-3.5 text-[var(--accent-pond)] shrink-0" />
          <h3 className="font-bold text-xs text-[var(--text-primary)] truncate tracking-tight">
            {cameraName ? `${cameraName} Tuning` : `Camera 0${cameraIndex} Tuning`}
          </h3>
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

      {/* Active Recording Notice */}
      {isRecording && (
        <div className="py-1 px-2 rounded-lg bg-red-500/10 border border-red-500/20 text-red-600 dark:text-red-400 text-[10px] font-bold flex items-center justify-between">
          <div className="flex items-center gap-1.5">
            <span className="w-1.5 h-1.5 rounded-full bg-red-500 animate-pulse" />
            <span>Recording Active</span>
          </div>
          <span className="text-[9px] font-normal opacity-85">Controls Locked</span>
        </div>
      )}

      {/* 2. Sensor Gain (ISO) - Logarithmic Scale */}
      <div className="py-1 px-2 rounded-lg bg-[var(--bg-card-subtle)] border border-[var(--border-color)] space-y-0.5">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1 text-[11px] font-bold text-[var(--text-primary)]">
            <Zap className="w-3 h-3 text-amber-500 fill-amber-500/20" />
            <span>Gain</span>
          </div>
          <div className="flex items-center gap-1">
            {hasIsoTelemetryDiff && (
              <span className="text-[9px] font-mono text-[var(--text-secondary)] bg-[var(--bg-card)] px-1 rounded border border-[var(--border-color)]" title="Hardware sensor applied sensitivity">
                Sensor: {appliedIso}
              </span>
            )}
            <span className="px-1.5 py-0.2 rounded font-mono text-[10px] font-bold bg-amber-500/10 text-amber-600 dark:text-amber-400 border border-amber-500/20">
              ISO {gain}
            </span>
          </div>
        </div>
        <input
          type="range"
          min={0}
          max={1000}
          step={1}
          value={valToLogPos(gain, gainHwMin, gainHwMax)}
          disabled={isRecording}
          onChange={(e) => {
            const nextVal = logPosToVal(parseInt(e.target.value, 10), gainHwMin, gainHwMax, 0);
            handleGainChange(nextVal);
          }}
          style={getLogSliderStyle(valToLogPos(gain, gainHwMin, gainHwMax))}
          className={`w-full h-1 rounded-lg ${isRecording ? 'opacity-40 cursor-not-allowed' : 'cursor-pointer'}`}
        />
        {gain > gainRecMax && (
          <div className="flex items-center gap-1 text-[9px] text-amber-500 font-medium pt-0.2">
            <AlertTriangle className="w-2.5 h-2.5 shrink-0" />
            <span>{getWarningMsg('gain', 'gt', 'High sensor noise and digital grain')}</span>
          </div>
        )}
      </div>

      {/* 3. Focus Lens - Linear 0 to 255 */}
      <div className="py-1 px-2 rounded-lg bg-[var(--bg-card-subtle)] border border-[var(--border-color)] space-y-0.5">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1 text-[11px] font-bold text-[var(--text-primary)]">
            <Focus className="w-3 h-3 text-[var(--accent-pond)]" />
            <span>Focus</span>
          </div>
          <span className="px-1.5 py-0.2 rounded font-mono text-[10px] font-bold bg-[var(--accent-pond-subtle)] text-[var(--accent-pond)] border border-[var(--accent-pond)]/30">
            {config.focusAvailable === false ? 'Auto' : focus}
          </span>
        </div>
        <input
          type="range"
          min={focusMin}
          max={focusMax}
          step={1}
          value={focus}
          disabled={isRecording || config.focusAvailable === false}
          onChange={(e) => handleFocusChange(parseInt(e.target.value, 10))}
          style={getLinearSliderStyle(focus, focusMin, focusMax)}
          className={`w-full h-1 rounded-lg ${isRecording || config.focusAvailable === false ? 'opacity-40 cursor-not-allowed' : 'cursor-pointer'}`}
        />
      </div>

      {/* 4. Exposure Shutter - Logarithmic Scale */}
      <div className="py-1 px-2 rounded-lg bg-[var(--bg-card-subtle)] border border-[var(--border-color)] space-y-0.5">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1 text-[11px] font-bold text-[var(--text-primary)]">
            <Sun className="w-3 h-3 text-[var(--accent-pond)]" />
            <span>Exposure</span>
          </div>
          <div className="flex items-center gap-1">
            {hasExpTelemetryDiff && (
              <span className="text-[9px] font-mono text-[var(--text-secondary)] bg-[var(--bg-card)] px-1 rounded border border-[var(--border-color)]" title="Hardware sensor applied exposure time">
                Sensor: {appliedExpMs}ms
              </span>
            )}
            <span className="px-1.5 py-0.2 rounded font-mono text-[10px] font-bold bg-[var(--accent-pond-subtle)] text-[var(--accent-pond)] border border-[var(--accent-pond)]/30">
              {exposure} ms
            </span>
          </div>
        </div>
        <input
          type="range"
          min={0}
          max={1000}
          step={1}
          value={valToLogPos(exposure, expHwMinMs, expHwMaxMs)}
          disabled={isRecording}
          onChange={(e) => {
            const nextVal = logPosToVal(parseInt(e.target.value, 10), expHwMinMs, expHwMaxMs, 1);
            handleExposureChange(nextVal);
          }}
          style={getLogSliderStyle(valToLogPos(exposure, expHwMinMs, expHwMaxMs))}
          className={`w-full h-1 rounded-lg ${isRecording ? 'opacity-40 cursor-not-allowed' : 'cursor-pointer'}`}
        />
        {isExpAboveFramePeriod ? (
          <div className="flex items-center gap-1 text-[9px] text-amber-500 font-medium pt-0.2">
            <AlertTriangle className="w-2.5 h-2.5 shrink-0" />
            <span>Exceeds frame period: stream will drop to ~{calcFps} FPS</span>
          </div>
        ) : isExpNearLimit ? (
          <div className="flex items-center gap-1 text-[9px] text-sky-400 font-medium pt-0.2">
            <Info className="w-2.5 h-2.5 shrink-0" />
            <span>{getWarningMsg('exposure', 'between', 'Near frame rate limit')}</span>
          </div>
        ) : null}
      </div>

      {/* 5. Tone (Digital Brightness & Hardware Contrast) */}
      <div className="py-1 px-2 rounded-lg bg-[var(--bg-card-subtle)] border border-[var(--border-color)] grid grid-cols-2 gap-2">
        <div>
          <div className="flex items-center justify-between text-[10px] font-medium text-[var(--text-secondary)] mb-0.5">
            <span title="Software digital luma post-processing">Brightness</span>
            <span className="font-mono font-bold text-[var(--accent-pond)] text-[9.5px]">
              {brightness > 0 ? `+${brightness}` : brightness}
            </span>
          </div>
          <input
            type="range"
            min={brightnessMin}
            max={brightnessMax}
            step={1}
            value={brightness}
            disabled={isRecording}
            onChange={(e) => handleBrightnessChange(parseInt(e.target.value, 10))}
            style={getLinearSliderStyle(brightness, brightnessMin, brightnessMax)}
            className={`w-full h-1 rounded-lg ${isRecording ? 'opacity-40 cursor-not-allowed' : 'cursor-pointer'}`}
          />
          {(brightness < brightnessRecMin || brightness > brightnessRecMax) && (
            <p className="text-[8.5px] text-amber-500 truncate pt-0.2" title={getWarningMsg('brightness', 'abs_gt', 'Digital luma shift reduces dynamic range')}>
              {getWarningMsg('brightness', 'abs_gt', 'Digital luma shift reduces dynamic range')}
            </p>
          )}
        </div>
        <div>
          <div className="flex items-center justify-between text-[10px] font-medium text-[var(--text-secondary)] mb-0.5">
            <span title="Hardware ISP Contrast register (-10 to +10)">Contrast</span>
            <span className="font-mono font-bold text-[var(--accent-pond)] text-[9.5px]">
              {contrast > 0 ? `+${contrast}` : contrast}
            </span>
          </div>
          <input
            type="range"
            min={contrastMin}
            max={contrastMax}
            step={1}
            value={contrast}
            disabled={isRecording}
            onChange={(e) => handleContrastChange(parseInt(e.target.value, 10))}
            style={getLinearSliderStyle(contrast, contrastMin, contrastMax)}
            className={`w-full h-1 rounded-lg ${isRecording ? 'opacity-40 cursor-not-allowed' : 'cursor-pointer'}`}
          />
          {contrast > contrastRecMax ? (
            <p className="text-[8.5px] text-amber-500 truncate pt-0.2" title={getWarningMsg('contrast', 'gt', 'Extreme contrast risks clipping specular highlights')}>
              {getWarningMsg('contrast', 'gt', 'Extreme contrast risks clipping specular highlights')}
            </p>
          ) : contrast < contrastRecMin ? (
            <p className="text-[8.5px] text-sky-400 truncate pt-0.2" title={getWarningMsg('contrast', 'lt', 'Low contrast creates a flat, washed-out image')}>
              {getWarningMsg('contrast', 'lt', 'Low contrast creates a flat, washed-out image')}
            </p>
          ) : null}
        </div>
      </div>

      {/* 6. Presets Row */}
      <div className="flex items-center gap-1 pt-0.5">
        <span className="text-[10px] font-bold text-[var(--text-secondary)] shrink-0">Presets:</span>
        <div className="flex items-center gap-1 flex-1">
          <button
            type="button"
            disabled={isRecording}
            onClick={() => handleApplyPreset('clean')}
            className={`flex-1 py-0.5 px-1 rounded-lg text-[9.5px] font-bold transition-all ${
              isRecording ? 'opacity-40 cursor-not-allowed' : 'cursor-pointer'
            } ${
              activePreset === 'clean'
                ? 'bg-[var(--accent-pond)] text-white shadow-xs'
                : 'bg-[var(--bg-card-subtle)] hover:bg-[var(--btn-secondary-hover)] text-[var(--text-primary)] border border-[var(--border-color)]'
            }`}
          >
            Clean
          </button>
          <button
            type="button"
            disabled={isRecording}
            onClick={() => handleApplyPreset('default')}
            className={`flex-1 py-0.5 px-1 rounded-lg text-[9.5px] font-bold transition-all ${
              isRecording ? 'opacity-40 cursor-not-allowed' : 'cursor-pointer'
            } ${
              activePreset === 'default'
                ? 'bg-[var(--accent-pond)] text-white shadow-xs'
                : 'bg-[var(--bg-card-subtle)] hover:bg-[var(--btn-secondary-hover)] text-[var(--text-primary)] border border-[var(--border-color)]'
            }`}
          >
            Default
          </button>
          <button
            type="button"
            disabled={isRecording}
            onClick={() => handleApplyPreset('night')}
            className={`flex-1 py-0.5 px-1 rounded-lg text-[9.5px] font-bold transition-all ${
              isRecording ? 'opacity-40 cursor-not-allowed' : 'cursor-pointer'
            } ${
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
          disabled={isRecording}
          onClick={handleReset}
          className={`h-7 px-2.5 rounded-xl bg-[var(--btn-secondary-bg)] border border-[var(--btn-secondary-border)] text-[var(--btn-secondary-text)] font-bold text-[11px] flex items-center gap-1 transition-colors shadow-2xs shrink-0 ${
            isRecording
              ? 'opacity-40 cursor-not-allowed'
              : 'hover:bg-[var(--btn-secondary-hover)] cursor-pointer active:scale-95'
          }`}
        >
          <RotateCcw className="w-3 h-3" />
          <span>Reset</span>
        </button>

        <button
          type="button"
          disabled={isSaving || isRecording}
          onClick={handleSaveSettings}
          className={`flex-1 h-7 rounded-xl bg-[var(--btn-primary-bg)] text-[var(--btn-primary-text)] border border-[var(--border-color)] font-bold text-[11px] flex items-center justify-center gap-1 shadow-xs transition-all ${
            isSaving || isRecording
              ? 'opacity-40 cursor-not-allowed'
              : 'hover:bg-[var(--btn-primary-hover)] cursor-pointer active:scale-95'
          }`}
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
