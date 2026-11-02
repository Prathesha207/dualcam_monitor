import React, { useState, useEffect } from 'react';
import type { CameraConfig } from '../types';
import { cameraService } from './service/cameraService';
import {
  X,
  Settings,
  FolderOpen,
  RefreshCw,
  Trash2,
  Check,
  Usb,
  Wifi,
  Sliders,
  CheckCircle2,
} from 'lucide-react';

interface CameraEditModalProps {
  isOpen: boolean;
  onClose: () => void;
  camera: CameraConfig | null;
  onSave: (updated: CameraConfig) => Promise<void> | void;
  onDelete?: (id: number) => Promise<void> | void;
}

interface HwDevice {
  mxid: string;
  name: string;
  ip_or_id: string;
  is_usb: boolean;
}

export const CameraEditModal: React.FC<CameraEditModalProps> = ({
  isOpen,
  onClose,
  camera,
  onSave,
  onDelete,
}) => {
  const [name, setName] = useState('');
  const [resolution, setResolution] = useState<'1920x1080' | '1280x720'>('1920x1080');
  const [targetFps, setTargetFps] = useState(30);
  const [recordingFormat, setRecordingFormat] = useState<'MP4' | 'AVI' | 'FFV1'>('MP4');
  const [storagePath, setStoragePath] = useState('');
  const [controlMode, setControlMode] = useState<'auto' | 'manual'>('auto');
  const [ipAddress, setIpAddress] = useState('');

  // Hardware re-assignment state
  const [availableDevices, setAvailableDevices] = useState<HwDevice[]>([]);
  const [isScanning, setIsScanning] = useState(false);
  const [isBrowsing, setIsBrowsing] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!isOpen || !camera) return;
    setName(camera.sourceName || '');
    setResolution((camera.resolution as any) || '1920x1080');
    setTargetFps(camera.targetFps || 30);
    setRecordingFormat(camera.recordingFormat || 'MP4');
    setStoragePath(camera.recordingVideoPath || '');
    setControlMode(camera.controlMode || 'auto');
    setIpAddress(camera.ipAddress || '');
    setError(null);
  }, [isOpen, camera]);

  const handleScanDevices = async () => {
    setIsScanning(true);
    try {
      const devices = await cameraService.getAvailableDevices();
      setAvailableDevices(Array.isArray(devices) ? devices : []);
    } catch {
      setAvailableDevices([]);
    } finally {
      setIsScanning(false);
    }
  };

  const handleBrowseFolder = async () => {
    setIsBrowsing(true);
    try {
      const res = await cameraService.browseFolder(storagePath);
      if (!res.canceled && res.path) {
        setStoragePath(res.path);
      }
    } catch (err: any) {
      console.warn('Folder browse failed:', err);
    } finally {
      setIsBrowsing(false);
    }
  };

  const handleSave = async () => {
    if (!camera) return;
    setIsSaving(true);
    setError(null);
    try {
      const updated: CameraConfig = {
        ...camera,
        sourceName: name.trim() || camera.sourceName,
        resolution,
        targetFps,
        recordingFormat,
        recordingVideoPath: storagePath.trim() || undefined,
        controlMode,
        ipAddress: ipAddress.trim() || camera.ipAddress,
      };

      await onSave(updated);
      onClose();
    } catch (err: any) {
      setError(err?.message || 'Failed to save camera changes');
    } finally {
      setIsSaving(false);
    }
  };

  if (!isOpen || !camera) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-4 bg-black/60 backdrop-blur-xs select-none animate-in fade-in duration-150">
      <div className="relative w-full max-w-lg rounded-2xl bg-[var(--bg-card)] border border-[var(--border-color)] shadow-xl overflow-hidden flex flex-col max-h-[90vh]">
        
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-3.5 border-b border-[var(--border-color)] bg-[var(--bg-card-subtle)]/50">
          <div className="flex items-center gap-2">
            <div className="flex items-center justify-center w-8 h-8 rounded-xl bg-[var(--accent-pond-subtle)] text-[var(--accent-pond)] border border-[var(--border-color)]">
              <Settings className="w-4 h-4" />
            </div>
            <div>
              <h3 className="font-bold text-sm sm:text-base text-[var(--text-primary)]">
                Edit Camera Settings
              </h3>
              <p className="text-[11px] text-[var(--text-secondary)]">
                Configure parameters for {camera.sourceName || 'this camera'}
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="flex items-center justify-center w-8 h-8 rounded-xl bg-[var(--btn-secondary-bg)] hover:bg-[var(--btn-secondary-hover)] text-[var(--text-secondary)] transition-all cursor-pointer"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Form Body */}
        <div className="flex-1 overflow-y-auto p-5 space-y-4">
          
          {error && (
            <div className="p-3 rounded-xl bg-[var(--status-anomaly-bg)] border border-[var(--status-anomaly-border)] text-[var(--status-anomaly-text)] text-xs font-medium">
              {error}
            </div>
          )}

          {/* 1. Camera Name */}
          <div>
            <label className="block text-xs font-bold text-[var(--text-primary)] mb-1.5">
              Camera Label / Name
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Front Door Camera"
              className="w-full px-3 py-2 rounded-xl bg-[var(--bg-card)] border border-[var(--border-color)] text-xs sm:text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent-pond)]"
            />
          </div>

          {/* 2. Hardware Assignment / Switch Device */}
          <div className="p-3.5 rounded-xl bg-[var(--bg-card-subtle)] border border-[var(--border-color)]">
            <div className="flex items-center justify-between mb-2">
              <label className="text-xs font-bold text-[var(--text-primary)] flex items-center gap-1.5">
                <Usb className="w-3.5 h-3.5 text-[var(--accent-pond)]" />
                <span>Connected Hardware Device</span>
              </label>
              <button
                type="button"
                onClick={handleScanDevices}
                disabled={isScanning}
                className="inline-flex items-center gap-1 text-[11px] font-bold text-[var(--accent-pond)] hover:underline cursor-pointer disabled:opacity-50"
              >
                <RefreshCw className={`w-3 h-3 ${isScanning ? 'animate-spin' : ''}`} />
                <span>Scan Devices</span>
              </button>
            </div>

            {availableDevices.length > 0 ? (
              <select
                value={ipAddress}
                onChange={(e) => setIpAddress(e.target.value)}
                className="w-full px-3 py-1.5 rounded-lg bg-[var(--bg-card)] border border-[var(--border-color)] text-xs text-[var(--text-primary)] focus:outline-none"
              >
                <option value={camera.ipAddress}>Current: {camera.ipAddress}</option>
                {availableDevices.map((d) => (
                  <option key={d.mxid || d.ip_or_id} value={d.ip_or_id}>
                    {d.name} ({d.ip_or_id})
                  </option>
                ))}
              </select>
            ) : (
              <input
                type="text"
                value={ipAddress}
                onChange={(e) => setIpAddress(e.target.value)}
                placeholder="MXID or IP Address"
                className="w-full px-3 py-1.5 rounded-lg bg-[var(--bg-card)] border border-[var(--border-color)] text-xs text-[var(--text-primary)] font-mono"
              />
            )}
          </div>

          {/* 3. Resolution & Target FPS */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-bold text-[var(--text-primary)] mb-1.5">
                Resolution
              </label>
              <div className="grid grid-cols-2 gap-1.5 p-1 rounded-xl bg-[var(--bg-card-subtle)] border border-[var(--border-color)]">
                <button
                  type="button"
                  onClick={() => setResolution('1920x1080')}
                  className={`py-1 text-center rounded-lg text-xs font-bold transition-all cursor-pointer ${
                    resolution === '1920x1080'
                      ? 'bg-[var(--bg-card)] text-[var(--accent-pond)] shadow-xs'
                      : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)]'
                  }`}
                >
                  1080p
                </button>
                <button
                  type="button"
                  onClick={() => setResolution('1280x720')}
                  className={`py-1 text-center rounded-lg text-xs font-bold transition-all cursor-pointer ${
                    resolution === '1280x720'
                      ? 'bg-[var(--bg-card)] text-[var(--accent-pond)] shadow-xs'
                      : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)]'
                  }`}
                >
                  720p
                </button>
              </div>
            </div>

            <div>
              <label className="block text-xs font-bold text-[var(--text-primary)] mb-1.5">
                Target Frame Rate ({targetFps} FPS)
              </label>
              <input
                type="range"
                min={10}
                max={60}
                step={5}
                value={targetFps}
                onChange={(e) => setTargetFps(parseInt(e.target.value, 10))}
                className="w-full accent-[var(--accent-pond)] mt-2 cursor-pointer"
              />
            </div>
          </div>

          {/* 4. Control Mode (Auto vs Manual) */}
          <div>
            <label className="block text-xs font-bold text-[var(--text-primary)] mb-1.5">
              Image Control Mode
            </label>
            <div className="grid grid-cols-2 gap-2">
              <button
                type="button"
                onClick={() => setControlMode('auto')}
                className={`flex items-center justify-center gap-1.5 p-2.5 rounded-xl border text-xs font-bold transition-all cursor-pointer ${
                  controlMode === 'auto'
                    ? 'bg-[var(--accent-pond-subtle)] border-[var(--accent-pond)] text-[var(--accent-pond)]'
                    : 'bg-[var(--bg-card)] border-[var(--border-color)] text-[var(--text-secondary)]'
                }`}
              >
                <span>AUTO (Camera adjusts)</span>
              </button>
              <button
                type="button"
                onClick={() => setControlMode('manual')}
                className={`flex items-center justify-center gap-1.5 p-2.5 rounded-xl border text-xs font-bold transition-all cursor-pointer ${
                  controlMode === 'manual'
                    ? 'bg-[var(--accent-pond-subtle)] border-[var(--accent-pond)] text-[var(--accent-pond)]'
                    : 'bg-[var(--bg-card)] border-[var(--border-color)] text-[var(--text-secondary)]'
                }`}
              >
                <span>MANUAL (Unlock sliders)</span>
              </button>
            </div>
          </div>

          {/* 5. Storage Path & Format */}
          <div>
            <label className="block text-xs font-bold text-[var(--text-primary)] mb-1.5">
              Folder Saving Path
            </label>
            <div className="flex items-center gap-1.5">
              <input
                type="text"
                value={storagePath}
                onChange={(e) => setStoragePath(e.target.value)}
                placeholder="Default: Desktop/DualCam_Recordings"
                className="flex-1 px-3 py-2 rounded-xl bg-[var(--bg-card)] border border-[var(--border-color)] text-xs text-[var(--text-primary)] font-mono focus:outline-none focus:border-[var(--accent-pond)]"
              />
              <button
                type="button"
                onClick={handleBrowseFolder}
                disabled={isBrowsing}
                title="Browse folder"
                className="flex items-center gap-1 px-3 py-2 rounded-xl bg-[var(--btn-secondary-bg)] hover:bg-[var(--btn-secondary-hover)] border border-[var(--btn-secondary-border)] text-xs font-bold text-[var(--btn-secondary-text)] transition-all cursor-pointer whitespace-nowrap active:scale-95"
              >
                <FolderOpen className="w-3.5 h-3.5" />
                <span>Browse</span>
              </button>
            </div>
          </div>

          {/* 6. Recording Format */}
          <div>
            <label className="block text-xs font-bold text-[var(--text-primary)] mb-1.5">
              Recording Container Format
            </label>
            <select
              value={recordingFormat}
              onChange={(e) => setRecordingFormat(e.target.value as any)}
              className="w-full px-3 py-2 rounded-xl bg-[var(--bg-card)] border border-[var(--border-color)] text-xs text-[var(--text-primary)] focus:outline-none"
            >
              <option value="MP4">MP4 (H.264 - Best compatibility)</option>
              <option value="AVI">AVI (MJPEG - Legacy / Machine Vision)</option>
              <option value="FFV1">MKV (FFV1 - Lossless)</option>
            </select>
          </div>

        </div>

        {/* Footer Actions */}
        <div className="flex items-center justify-between px-5 py-3 border-t border-[var(--border-color)] bg-[var(--bg-card-subtle)]/50">
          {onDelete && camera.id ? (
            <button
              type="button"
              onClick={() => {
                if (window.confirm(`Delete ${camera.sourceName || 'this camera'}?`)) {
                  onDelete(camera.id!);
                  onClose();
                }
              }}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-bold text-[var(--status-anomaly-text)] hover:bg-[var(--status-anomaly-bg)] transition-all cursor-pointer"
            >
              <Trash2 className="w-3.5 h-3.5" />
              <span>Delete Camera</span>
            </button>
          ) : <div />}

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 rounded-xl bg-[var(--btn-secondary-bg)] hover:bg-[var(--btn-secondary-hover)] border border-[var(--btn-secondary-border)] text-xs font-bold text-[var(--btn-secondary-text)] transition-all cursor-pointer"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={handleSave}
              disabled={isSaving}
              className="inline-flex items-center gap-1.5 px-5 py-2 rounded-xl bg-[var(--btn-primary-bg)] text-[var(--btn-primary-text)] text-xs font-bold shadow-xs hover:opacity-90 active:scale-95 transition-all cursor-pointer disabled:opacity-50"
            >
              <Check className="w-3.5 h-3.5 stroke-[2.5]" />
              <span>{isSaving ? 'Saving...' : 'Save Changes'}</span>
            </button>
          </div>
        </div>

      </div>
    </div>
  );
};

