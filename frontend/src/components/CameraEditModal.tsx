import React, { useState, useEffect } from 'react';
import type { CameraConfig } from '../types';
import { cameraService } from './service/cameraService';
import {
  Camera,
  Check,
  FolderOpen,
  RefreshCw,
  Trash2,
  Usb,
  Wifi,
  HardDrive,
  Loader2,
  AlertCircle,
  Power,
  Radio,
  Lock,
} from 'lucide-react';
import { Modal, Button, NumberStepper } from './ui';

interface CameraEditModalProps {
  isOpen: boolean;
  onClose: () => void;
  camera: CameraConfig | null;
  onSave: (updated: CameraConfig) => Promise<void> | void;
  onDelete?: (id: number) => Promise<void> | void;
  isRecording?: boolean;
  existingCameras?: CameraConfig[];
}

interface HwDevice {
  mxid: string;
  name: string;
  ip_or_id: string;
  is_usb: boolean;
  protocol?: string;
}

export const CameraEditModal: React.FC<CameraEditModalProps> = ({
  isOpen,
  onClose,
  camera,
  onSave,
  onDelete,
  isRecording = false,
  existingCameras = [],
}) => {
  // Camera parameters
  const [name, setName] = useState('');
  const [clipDurationMinutes, setClipDurationMinutes] = useState(1);
  const [connectionType, setConnectionType] = useState<'usb' | 'ip'>('usb');
  const [ipAddress, setIpAddress] = useState('');
  const [resolution, setResolution] = useState<'1920x1080' | '1280x720'>('1920x1080');
  const [targetFps, setTargetFps] = useState(30);
  const [recordingFormat, setRecordingFormat] = useState<'MP4' | 'AVI' | 'FFV1'>('MP4');
  const [storagePath, setStoragePath] = useState('');
  const [defaultDesktopPath, setDefaultDesktopPath] = useState('');
  const [controlMode, setControlMode] = useState<'auto' | 'manual'>('auto');
  const [isEnabled, setIsEnabled] = useState(true);

  // Manual image adjustments
  const [exposure, setExposure] = useState(8);
  const [gain, setGain] = useState(400);
  const [focus, setFocus] = useState(0);
  const [brightness, setBrightness] = useState(0);
  const [contrast, setContrast] = useState(50);

  // Hardware scan & loading states
  const [availableDevices, setAvailableDevices] = useState<HwDevice[]>([]);
  const [isScanning, setIsScanning] = useState(false);
  const [isBrowsingFolder, setIsBrowsingFolder] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  useEffect(() => {
    if (!isOpen || !camera) {
      setErrorMessage(null);
      setIsDeleting(false);
      return;
    }

    setName(camera.sourceName || '');
    setClipDurationMinutes(camera.clipDurationMinutes || 1);
    const isIp = Boolean(camera.ipAddress && camera.ipAddress.includes('.') && !camera.ipAddress.toLowerCase().includes('usb'));
    setConnectionType(isIp ? 'ip' : 'usb');
    setIpAddress(camera.ipAddress || '');
    setResolution((camera.resolution as any) || '1920x1080');
    setTargetFps(camera.targetFps || 30);
    setRecordingFormat((camera.recordingFormat as any) || 'MP4');
    setStoragePath(camera.recordingVideoPath || '');
    setControlMode(camera.controlMode || 'auto');
    setIsEnabled(camera.is_enabled !== false);

    // Live adjustments
    setExposure(camera.exposure ?? 8);
    setGain(camera.gain ?? camera.iso ?? 400);
    setFocus(camera.focus ?? 0);
    setBrightness(camera.brightness ?? 0);
    setContrast(camera.contrast ?? 50);

    // Load default desktop storage path
    cameraService
      .getStoragePath()
      .then((res) => {
        if (res?.default_path) setDefaultDesktopPath(res.default_path);
        if (!camera.recordingVideoPath && res?.storage_path) {
          setStoragePath(res.storage_path);
        }
      })
      .catch(() => {});

    // Quick initial device scan
    handleScanDevices();
  }, [isOpen, camera]);

  const handleScanDevices = async () => {
    setIsScanning(true);
    try {
      const devices = await cameraService.getAvailableDevices().catch(() => []);
      setAvailableDevices(Array.isArray(devices) ? devices : []);
    } finally {
      setIsScanning(false);
    }
  };

  const handleBrowseFolder = async () => {
    setIsBrowsingFolder(true);
    try {
      const res = await cameraService.browseFolder(storagePath || defaultDesktopPath);
      if (res && res.path && !res.canceled) {
        setStoragePath(res.path);
      }
    } catch (err: any) {
      console.warn('Folder browse failed:', err);
    } finally {
      setIsBrowsingFolder(false);
    }
  };

  const handleResetDesktop = async () => {
    let p = defaultDesktopPath;
    if (!p) {
      try {
        const res = await cameraService.getStoragePath();
        p = res?.default_path || '';
        if (p) setDefaultDesktopPath(p);
      } catch {}
    }
    if (p) {
      setStoragePath(p);
    }
  };

  // Direct Delete: No localhost prompt!
  const handleDelete = async () => {
    if (!camera?.id || !onDelete) return;
    setIsDeleting(true);
    try {
      await onDelete(camera.id);
      onClose();
    } catch (err: any) {
      setErrorMessage(err?.message || 'Failed to delete camera');
      setIsDeleting(false);
    }
  };

  const handleSave = async () => {
    if (!camera) return;
    setIsSaving(true);
    setErrorMessage(null);

    const cleanName = name.trim();
    if (!cleanName) {
      setErrorMessage('Camera name cannot be empty.');
      setIsSaving(false);
      return;
    }

    const normTarget = cleanName.replace(/[\s_\-]+/g, '').toLowerCase();
    if (
      existingCameras &&
      existingCameras.some(
        (c) => c.id !== camera.id && (c.sourceName || '').replace(/[\s_\-]+/g, '').toLowerCase() === normTarget
      )
    ) {
      setErrorMessage(`Camera name "${cleanName}" is already in use by another camera. Dual cameras must have different names.`);
      setIsSaving(false);
      return;
    }

    const chosenIp =
      connectionType === 'usb'
        ? (availableDevices.find((d) => d.is_usb)?.ip_or_id || ipAddress || 'usb')
        : ipAddress.trim();

    try {
      const updated: CameraConfig = {
        ...camera,
        sourceName: cleanName,
        ipAddress: chosenIp,
        resolution,
        targetFps,
        recordingFormat,
        recordingVideoPath: storagePath.trim() || undefined,
        clipDurationMinutes: Math.max(1, clipDurationMinutes || 1),
        controlMode,
        is_enabled: isEnabled,
        exposure,
        gain,
        iso: gain,
        focus,
        brightness,
        contrast,
      };

      // Also persist live image controls if changed
      if (camera.id && (exposure !== camera.exposure || gain !== camera.gain || focus !== camera.focus)) {
        await cameraService.updateLiveControls(camera.id, {
          exposure,
          gain,
          focus,
          brightness,
          contrast,
          control_mode: controlMode,
          save_to_db: true,
        }).catch(() => {});
      }

      await onSave(updated);
      onClose();
    } catch (err: any) {
      setErrorMessage(err?.message || 'Failed to save camera parameters');
    } finally {
      setIsSaving(false);
    }
  };

  const getSliderStyle = (val: number, min: number, max: number) => {
    const pct = Math.max(0, Math.min(100, ((val - min) / (max - min)) * 100));
    return {
      background: `linear-gradient(to right, var(--accent-pond) 0%, var(--accent-pond) ${pct}%, var(--border-color) ${pct}%, var(--border-color) 100%)`,
      accentColor: 'var(--accent-pond)',
    };
  };

  if (!isOpen || !camera) return null;

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      maxWidth="xl"
      icon={<Camera className="w-4 h-4 text-[var(--accent-pond)]" />}
      title="Camera & Stream Settings"
      description={`Configure parameters for ${camera.sourceName || camera.ipAddress || 'this camera'}`}
      footer={
        <div className="flex items-center justify-between w-full">
          {/* Delete Camera: Immediate clean delete, NO localhost confirm! */}
          {onDelete && camera.id ? (
            <Button
              variant="secondary"
              size="sm"
              onClick={handleDelete}
              disabled={isDeleting || isSaving}
              className="h-8 px-3 text-xs font-bold text-red-600 dark:text-red-400 border-red-500/30 hover:bg-red-500/10 cursor-pointer"
              icon={isDeleting ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Trash2 className="w-3.5 h-3.5" />}
            >
              <span>{isDeleting ? 'Deleting...' : 'Delete Camera'}</span>
            </Button>
          ) : <div />}

          <div className="flex items-center gap-2">
            <Button
              variant="ghost"
              size="sm"
              onClick={onClose}
              disabled={isSaving || isDeleting}
              className="h-8 px-3.5 text-xs font-medium cursor-pointer"
            >
              Cancel
            </Button>
            <Button
              variant="primary"
              size="sm"
              onClick={handleSave}
              disabled={isSaving || isDeleting}
              className="h-8 px-4 text-xs font-bold cursor-pointer"
              icon={isSaving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Check className="w-3.5 h-3.5" />}
            >
              <span>{isSaving ? 'Saving...' : 'Save Changes'}</span>
            </Button>
          </div>
        </div>
      }
    >
      {errorMessage && (
        <div className="mb-3 p-2.5 rounded-xl bg-rose-500/10 border border-rose-500/30 text-rose-600 dark:text-rose-400 text-xs flex items-center gap-2 font-medium">
          <AlertCircle className="w-4 h-4 shrink-0 text-rose-500" />
          <span>{errorMessage}</span>
        </div>
      )}

      <div className="space-y-3">
          
          {/* 1. Stream Output Profile (Resolution, FPS, Video Format) */}
          <div className="p-3 rounded-2xl bg-[var(--bg-card-subtle)] border border-[var(--border-color)] space-y-3">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              
              {/* Resolution Pills */}
              <div className="space-y-1">
                <div className="text-[10px] font-bold text-[var(--text-secondary)] uppercase tracking-wider">
                  Resolution
                </div>
                <div className="inline-flex items-center gap-1 p-0.5 rounded-xl bg-[var(--bg-card)] border border-[var(--border-color)] w-full">
                  {(['1920x1080', '1280x720'] as const).map((res) => {
                    const isSelected = resolution === res;
                    return (
                      <button
                        key={res}
                        type="button"
                        onClick={() => setResolution(res)}
                        className={`flex-1 py-1.5 px-2 rounded-lg text-xs font-bold transition-all cursor-pointer text-center ${
                          isSelected
                            ? 'bg-[var(--accent-pond)] text-white shadow-xs'
                            : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)]'
                        }`}
                      >
                        {res === '1920x1080' ? '1080p FHD' : '720p HD'}
                      </button>
                    );
                  })}
                </div>
              </div>

              {/* Target FPS Slider */}
              <div className="space-y-1 flex flex-col justify-between">
                <div className="flex items-center justify-between text-[10px] font-bold text-[var(--text-secondary)] uppercase tracking-wider">
                  <span>Frame Count</span>
                  <span className="font-mono font-bold text-[var(--accent-pond)] px-1.5 py-0.5 rounded bg-[var(--bg-card)] border border-[var(--border-color)]">
                    {targetFps} FPS
                  </span>
                </div>
                <div className="h-[31px] flex items-center px-2.5 rounded-xl bg-[var(--bg-card)] border border-[var(--border-color)]">
                  <input
                    type="range"
                    min={5}
                    max={60}
                    step={1}
                    value={targetFps}
                    onChange={(e) => setTargetFps(parseInt(e.target.value, 10))}
                    style={getSliderStyle(targetFps, 5, 60)}
                    className="w-full h-1.5 rounded cursor-pointer transition-all"
                  />
                </div>
              </div>

              {/* Recording Video Format Pills */}
              <div className="sm:col-span-2 space-y-1 pt-2 border-t border-[var(--border-color)]/60">
                <div className="flex items-center justify-between">
                  <span className="text-[10px] font-bold text-[var(--text-secondary)] uppercase tracking-wider">
                    Recording Video Format
                  </span>
                  <span className="text-[10px] font-semibold text-[var(--accent-pond)]">
                    {recordingFormat === 'MP4'
                      ? 'MP4 container • H.264 web/universal codec'
                      : recordingFormat === 'AVI'
                      ? 'AVI container • MJPEG analytical codec'
                      : 'MKV container • FFV1 lossless codec'}
                  </span>
                </div>
                <div className="inline-flex items-center gap-1 p-0.5 rounded-xl bg-[var(--bg-card)] border border-[var(--border-color)] w-full">
                  {([
                    { id: 'MP4', label: 'MP4 (H.264)' },
                    { id: 'AVI', label: 'AVI (MJPEG)' },
                    { id: 'FFV1', label: 'MKV (FFV1)' },
                  ] as const).map((fmt) => {
                    const isSelected = recordingFormat === fmt.id;
                    return (
                      <button
                        key={fmt.id}
                        type="button"
                        onClick={() => setRecordingFormat(fmt.id)}
                        className={`flex-1 py-1.5 px-2 rounded-lg text-xs font-bold transition-all cursor-pointer text-center ${
                          isSelected
                            ? 'bg-[var(--accent-pond)] text-white shadow-xs'
                            : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)]'
                        }`}
                      >
                        {fmt.label}
                      </button>
                    );
                  })}
                </div>
              </div>

              {/* Clip Split Interval Stepper */}
              <div className="sm:col-span-2 space-y-1 pt-2 border-t border-[var(--border-color)]/60">
                <div className="flex items-center justify-between">
                  <div>
                    <span className="text-[10px] font-bold text-[var(--text-secondary)] uppercase tracking-wider block">
                      Clip Split Interval
                    </span>
                    <span className="text-[10px] text-[var(--text-muted)]">
                      Saves continuous video into separate clips. Balance minutes are safely saved when stopped.
                    </span>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <NumberStepper
                      value={clipDurationMinutes}
                      onChange={(val) => setClipDurationMinutes(val)}
                      min={1}
                      max={180}
                      step={1}
                      size="sm"
                    />
                    <span className="text-xs font-mono font-bold text-[var(--text-secondary)]">min</span>
                  </div>
                </div>
              </div>

              {/* Output Storage Directory */}
              <div className="sm:col-span-2 space-y-1.5 pt-2 border-t border-[var(--border-color)]/60">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-1.5">
                    <FolderOpen className="w-3.5 h-3.5 text-[var(--accent-pond)]" />
                    <span className="text-[10px] font-bold text-[var(--text-secondary)] uppercase tracking-wider">
                      Output Storage Directory
                    </span>
                  </div>
                  <span className="text-[10px] font-semibold text-[var(--accent-pond)] flex items-center gap-1">
                    <HardDrive className="w-3 h-3" />
                    {storagePath && defaultDesktopPath && storagePath.toLowerCase() === defaultDesktopPath.toLowerCase()
                      ? 'Default (Desktop)'
                      : 'Custom PC Folder'}
                  </span>
                </div>

                <div className="flex items-center gap-2 w-full">
                  <input
                    type="text"
                    value={storagePath}
                    onChange={(e) => setStoragePath(e.target.value)}
                    placeholder={defaultDesktopPath || 'C:\\Users\\...\\Desktop'}
                    className="flex-1 min-w-0 text-xs font-mono px-3 py-2 rounded-xl bg-[var(--bg-card)] border border-[var(--border-color)] text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent-pond)] focus:ring-1 focus:ring-[var(--accent-pond)]"
                  />
                  <button
                    type="button"
                    onClick={handleBrowseFolder}
                    disabled={isBrowsingFolder}
                    title="Browse PC folders"
                    className="inline-flex items-center justify-center gap-1.5 h-9 px-3.5 rounded-xl bg-[var(--bg-card)] hover:bg-[var(--accent-pond-subtle)] text-[var(--accent-pond)] border border-[var(--border-color)] hover:border-[var(--accent-pond)] text-xs font-bold transition-all cursor-pointer whitespace-nowrap shrink-0 active:scale-95 disabled:opacity-50"
                  >
                    {isBrowsingFolder ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <FolderOpen className="w-3.5 h-3.5" />}
                    <span>Browse...</span>
                  </button>
                  <button
                    type="button"
                    onClick={handleResetDesktop}
                    title="Reset to default Desktop folder"
                    className="inline-flex items-center justify-center h-9 px-3 rounded-xl bg-[var(--bg-card)] hover:bg-[var(--bg-card-subtle)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] border border-[var(--border-color)] text-xs font-medium transition-all cursor-pointer whitespace-nowrap shrink-0 active:scale-95"
                  >
                    Desktop
                  </button>
                </div>
                <p className="text-[10px] text-[var(--text-muted)]">
                  Camera recordings and snapshots save here automatically.
                </p>
              </div>

            </div>
          </div>

          {/* 2. Camera Connection & Hardware Settings */}
          <div className="p-3.5 rounded-2xl bg-[var(--bg-card)] border border-[var(--border-color)] space-y-3">
            <div className="flex items-center justify-between pb-1.5 border-b border-[var(--border-color)]">
              <div className="flex items-center gap-1.5">
                <div className="w-5 h-5 rounded-md bg-[var(--accent-pond-subtle)] text-[var(--accent-pond)] flex items-center justify-center border border-[var(--border-color)]">
                  <Radio className="w-3 h-3" />
                </div>
                <span className="text-xs font-bold text-[var(--text-primary)]">
                  Hardware Connection
                </span>
              </div>

              {/* Interface Switcher Pills */}
              <div className="inline-flex items-center gap-1 p-0.5 rounded-lg bg-[var(--bg-card-subtle)] border border-[var(--border-color)]">
                <button
                  type="button"
                  onClick={() => setConnectionType('usb')}
                  className={`px-2.5 py-0.5 rounded-md text-[11px] font-bold flex items-center gap-1 transition-all cursor-pointer ${
                    connectionType === 'usb'
                      ? 'bg-[var(--accent-pond)] text-white shadow-xs'
                      : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)]'
                  }`}
                >
                  <Usb className="w-3 h-3" /> USB
                </button>
                <button
                  type="button"
                  onClick={() => setConnectionType('ip')}
                  className={`px-2.5 py-0.5 rounded-md text-[11px] font-bold flex items-center gap-1 transition-all cursor-pointer ${
                    connectionType === 'ip'
                      ? 'bg-[var(--accent-pond)] text-white shadow-xs'
                      : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)]'
                  }`}
                >
                  <Wifi className="w-3 h-3" /> IP / PoE
                </button>
              </div>
            </div>

            {/* Camera Label & Control Mode */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div>
                <div className="flex items-center justify-between mb-1">
                  <label className="block text-[10px] font-bold text-[var(--text-secondary)] uppercase tracking-wider">
                    Camera Label
                  </label>
                  {isRecording && (
                    <span className="text-[10px] text-amber-500 font-bold flex items-center gap-1">
                      <Lock className="w-3 h-3" /> Locked during recording
                    </span>
                  )}
                </div>
                <input
                  type="text"
                  value={name}
                  disabled={isRecording}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="e.g., Front_Door"
                  className={`w-full h-9 px-3 text-xs rounded-xl bg-[var(--bg-card-subtle)] border border-[var(--border-color)] text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent-pond)] ${
                    isRecording ? 'opacity-50 cursor-not-allowed' : ''
                  }`}
                />
                <p className="text-[10px] text-[var(--text-muted)] mt-1 truncate">
                  Recordings folder: <span className="font-mono text-[var(--accent-pond)]">{name.trim().replace(/\s+/g, '_') || 'Camera'}/</span>
                </p>
              </div>

              <div>
                <label className="block text-[10px] font-bold text-[var(--text-secondary)] uppercase tracking-wider mb-1">
                  Image Control Mode
                </label>
                <div className="grid grid-cols-2 gap-1 p-0.5 rounded-xl bg-[var(--bg-card-subtle)] border border-[var(--border-color)] h-9 items-center">
                  <button
                    type="button"
                    onClick={() => setControlMode('auto')}
                    className={`h-7 text-center rounded-lg text-xs font-bold transition-all cursor-pointer ${
                      controlMode === 'auto'
                        ? 'bg-[var(--accent-pond)] text-white shadow-xs'
                        : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)]'
                    }`}
                  >
                    AUTO
                  </button>
                  <button
                    type="button"
                    onClick={() => setControlMode('manual')}
                    className={`h-7 text-center rounded-lg text-xs font-bold transition-all cursor-pointer ${
                      controlMode === 'manual'
                        ? 'bg-[var(--accent-pond)] text-white shadow-xs'
                        : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)]'
                    }`}
                  >
                    MANUAL
                  </button>
                </div>
              </div>
            </div>

            {/* Hardware Address & Scan Row on EXACT SAME LINE */}
            <div className="space-y-1">
              <div className="flex items-center justify-between">
                <label className="text-[10px] font-bold text-[var(--text-secondary)] uppercase tracking-wider">
                  {connectionType === 'usb' ? 'Connected Hardware Device' : 'Device IP Address / Hostname'}
                </label>
                {availableDevices.length > 0 && (
                  <span className="text-[10px] text-emerald-600 dark:text-emerald-400 font-semibold">
                    {availableDevices.length} device{availableDevices.length > 1 ? 's' : ''} detected
                  </span>
                )}
              </div>

              <div className="flex items-center gap-2 w-full">
                {connectionType === 'usb' ? (
                  <div className="relative flex-1 min-w-0">
                    <select
                      value={availableDevices.some((d) => d.ip_or_id === (ipAddress || camera.ipAddress)) ? (ipAddress || camera.ipAddress) : ''}
                      onChange={(e) => {
                        const chosen = availableDevices.find((d) => d.ip_or_id === e.target.value);
                        if (chosen) {
                          setIpAddress(chosen.ip_or_id);
                          if (!name.trim()) setName(chosen.name);
                        }
                      }}
                      className="w-full h-9 text-xs px-3 rounded-xl bg-[var(--bg-card-subtle)] border border-[var(--border-color)] text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent-pond)] truncate"
                    >
                      <option value="">
                        {availableDevices.length > 0
                          ? `Select detected device (${availableDevices[0].name})...`
                          : (camera.ipAddress ? `Connected: ${camera.ipAddress}` : 'Auto-detect USB Device')}
                      </option>
                      {availableDevices.map((dev, i) => (
                        <option key={dev.mxid || i} value={dev.ip_or_id}>
                          {dev.name} ({dev.protocol || (dev.is_usb ? 'USB' : 'PoE')})
                        </option>
                      ))}
                    </select>
                  </div>
                ) : (
                  <input
                    type="text"
                    value={ipAddress}
                    onChange={(e) => setIpAddress(e.target.value)}
                    placeholder="e.g. 169.254.21.191"
                    className="flex-1 min-w-0 h-9 px-3 text-xs font-mono rounded-xl bg-[var(--bg-card-subtle)] border border-[var(--border-color)] text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent-pond)]"
                  />
                )}

                <button
                  type="button"
                  onClick={handleScanDevices}
                  disabled={isScanning}
                  title="Scan for connected hardware cameras"
                  className="inline-flex items-center justify-center gap-1.5 h-9 px-3.5 rounded-xl bg-[var(--bg-card-subtle)] hover:bg-[var(--accent-pond-subtle)] text-[var(--accent-pond)] border border-[var(--border-color)] hover:border-[var(--accent-pond)] text-xs font-bold transition-all cursor-pointer whitespace-nowrap shrink-0 active:scale-95 disabled:opacity-50"
                >
                  <RefreshCw className={`w-3.5 h-3.5 ${isScanning ? 'animate-spin' : ''}`} />
                  <span>Scan</span>
                </button>
              </div>
            </div>

            {/* Hardware Power Toggle */}
            <div className="pt-2 border-t border-[var(--border-color)]/60 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Power className={`w-4 h-4 ${isEnabled ? 'text-emerald-500' : 'text-slate-400'}`} />
                <div>
                  <span className="text-xs font-bold text-[var(--text-primary)] block">
                    Hardware Status
                  </span>
                  <span className="text-[10px] text-[var(--text-muted)]">
                    {isEnabled ? 'Camera hardware is enabled & active' : 'Camera is disabled (resources released)'}
                  </span>
                </div>
              </div>

              <button
                type="button"
                onClick={() => setIsEnabled(!isEnabled)}
                className={`px-3 py-1 rounded-xl text-xs font-bold border transition-all cursor-pointer ${
                  isEnabled
                    ? 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border-emerald-500/30'
                    : 'bg-[var(--bg-card-subtle)] text-[var(--text-secondary)] border-[var(--border-color)]'
                }`}
              >
                {isEnabled ? '● Enabled' : '○ Disabled'}
              </button>
            </div>

          </div>

        </div>

    </Modal>
  );
};
