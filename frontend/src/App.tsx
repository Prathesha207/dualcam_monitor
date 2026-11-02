import React, { useState, useEffect, useCallback, useRef } from 'react';
import type { ThemeMode, CameraConfig } from './types';
import { LandingScreen } from './components/LandingScreen';
import { Header } from './components/Header';
import { CameraCard } from './components/CameraCard';
import { CameraImageAdjustmentsCard } from './components/CameraImageAdjustmentsCard';
import { CameraSettingsModal } from './components/CameraSettingsModal';
import { CameraEditModal } from './components/CameraEditModal';
import { HelpModal } from './components/HelpModal';
import { Toast } from './components/ui';
import { cameraService } from './components/service/cameraService';
import { recordingService } from './components/service/recordingService';
import { Plus, Camera, SlidersHorizontal } from 'lucide-react';

// Extracted hooks
import { useBackendHealth } from './hooks/useBackendHealth';
import { useToastAndLogs } from './hooks/useToastAndLogs';

export default function App() {
  // ─── 1. System Health & Landing ─────────────────────────────────────
  const { systemInitialized, setSystemInitialized, handleInitializeSystem } = useBackendHealth();

  // ─── 2. Toast Notifications & Activity Logs ────────────────────────
  const { toast, setToast, showToast, addLog } = useToastAndLogs();

  // ─── 3. Theme & UI Shell ───────────────────────────────────────────
  const [theme, setTheme] = useState<ThemeMode>(() => {
    if (typeof window !== 'undefined') {
      const saved = localStorage.getItem('visionmonitor-theme') as ThemeMode | null;
      if (saved && (saved === 'pond-light' || saved === 'pond-dark' || saved === 'nature')) {
        return saved;
      }
    }
    return 'pond-light';
  });

  const handleThemeChange = (newTheme: ThemeMode) => {
    if (typeof document !== 'undefined') {
      document.documentElement.setAttribute('data-theme', newTheme);
      document.body.setAttribute('data-theme', newTheme);
      const themeClass =
        newTheme === 'pond-dark'
          ? 'theme-pond-dark dark'
          : newTheme === 'nature'
          ? 'theme-nature dark'
          : 'theme-pond-light';
      document.documentElement.className = themeClass;
      document.body.className = themeClass;
      try {
        localStorage.setItem('visionmonitor-theme', newTheme);
      } catch {}
    }
    setTheme(newTheme);
  };

  // ─── 4. Multi-Camera State ─────────────────────────────────────────
  const [cameras, setCameras] = useState<CameraConfig[]>([]);
  const [streamingStates, setStreamingStates] = useState<Record<number, boolean>>({});
  const [startingStates, setStartingStates] = useState<Record<number, boolean>>({});
  const [recordingStates, setRecordingStates] = useState<
    Record<number, { isRecording: boolean; duration: number; sessionId: string }>
  >({});

  const [expandedCameraId, setExpandedCameraId] = useState<number | null>(null);
  const [activeControlsCamera, setActiveControlsCamera] = useState<CameraConfig | null>(null);
  const [connectionErrors, setConnectionErrors] = useState<Record<number, string | null>>({});
  const [editCamera, setEditCamera] = useState<CameraConfig | null>(null);
  const [addCameraOpen, setAddCameraOpen] = useState<boolean>(false);
  const [helpOpen, setHelpOpen] = useState<boolean>(false);

  // ─── 5. Load Cameras from Database ─────────────────────────────────
  const refreshCameras = useCallback(async () => {
    try {
      const dbCameras = await cameraService.checkCamera();
      if (Array.isArray(dbCameras)) {
        const mapped: CameraConfig[] = dbCameras.map((c: any) => ({
          id: c.id,
          sourceName: c.name || `Camera ${c.id}`,
          ipAddress: c.ip_address || '',
          resolution: (c.resolution as any) || '1920x1080',
          targetFps: c.fps || 30,
          rotationAngle: c.rotation_angle ?? 0,
          controlMode: (c.control_mode as any) || 'auto',
          exposure: c.exposure ?? 8,
          gain: c.gain ?? 400,
          iso: c.gain ?? 400,
          focus: c.focus ?? 0,
          focusAvailable: c.focus !== null && c.focus !== undefined,
          brightness: c.brightness ?? 0,
          contrast: c.contrast ?? 50,
          autoFocus: false,
          autoExposure: false,
          connected: false,
          is_enabled: c.is_enabled !== false,
          recordingFormat: (c.recording_format as any) || 'MP4',
          recordingVideoPath: c.recording_video_path || null,
        }));
        setCameras(mapped);
      }
    } catch (err: any) {
      console.warn('Failed to load cameras from database:', err);
    }
  }, []);

  useEffect(() => {
    if (systemInitialized) {
      refreshCameras();
      // Probe active hardware stream state from backend
      cameraService.health().then((h) => {
        if (h && (h.running || h.streaming)) {
          const allCams = h.all_cameras || {};
          setStreamingStates((prev) => {
            const next = { ...prev };
            Object.keys(allCams).forEach((cid) => {
              if (allCams[cid]?.streaming || allCams[cid]?.running) {
                next[Number(cid)] = true;
              }
            });
            return next;
          });
        }
      }).catch(() => {});
    }
  }, [systemInitialized, refreshCameras]);

  // ─── 6. Recording Duration Tick (Every 1s) ─────────────────────────
  useEffect(() => {
    const timer = setInterval(() => {
      setRecordingStates((prev) => {
        let changed = false;
        const next = { ...prev };
        Object.keys(next).forEach((key) => {
          const id = Number(key);
          if (next[id]?.isRecording) {
            next[id] = { ...next[id], duration: (next[id].duration || 0) + 1 };
            changed = true;
          }
        });
        return changed ? next : prev;
      });
    }, 1000);
    return () => clearInterval(timer);
  }, []);

  // ─── 7. Stream Action Handlers ─────────────────────────────────────
  const handleStartStream = useCallback(
    async (id: number) => {
      setStartingStates((prev) => ({ ...prev, [id]: true }));
      try {
        const cam = cameras.find((c) => c.id === id);
        await cameraService.start({ camera_id: id, ip_address: cam?.ipAddress });
        await cameraService.startStream(id);
        setStreamingStates((prev) => ({ ...prev, [id]: true }));
        setConnectionErrors((prev) => ({ ...prev, [id]: null }));
        showToast('success', `${cam?.sourceName || `Camera ${id}`} live stream started`);
        addLog(`Started live stream for camera ${id}`, 'info');
      } catch (err: any) {
        const msg = err?.message || `Failed to start stream on Camera ${id}`;
        setConnectionErrors((prev) => ({ ...prev, [id]: msg }));
        showToast('error', msg);
      } finally {
        setStartingStates((prev) => ({ ...prev, [id]: false }));
      }
    },
    [cameras, showToast, addLog]
  );

  const handleStopStream = useCallback(
    async (id: number) => {
      try {
        // If recording on this camera, stop recording first
        if (recordingStates[id]?.isRecording) {
          const sid = recordingStates[id].sessionId;
          await recordingService.stopRecording(sid, id).catch(() => {});
          setRecordingStates((prev) => ({ ...prev, [id]: { isRecording: false, duration: 0, sessionId: '' } }));
        }

        await cameraService.stopStream(id);
        setStreamingStates((prev) => ({ ...prev, [id]: false }));
        const cam = cameras.find((c) => c.id === id);
        showToast('info', `${cam?.sourceName || `Camera ${id}`} live stream stopped`);
        addLog(`Stopped live stream for camera ${id}`, 'info');
      } catch (err: any) {
        showToast('error', err?.message || `Failed to stop stream on Camera ${id}`);
      }
    },
    [cameras, recordingStates, showToast, addLog]
  );

  // ─── 8. Hardware Enable / Disable ──────────────────────────────────
  const handleToggleEnable = useCallback(
    async (id: number, currentEnabled: boolean) => {
      try {
        setConnectionErrors((prev) => ({ ...prev, [id]: null }));
        if (currentEnabled) {
          // Disable hardware
          if (streamingStates[id]) {
            await handleStopStream(id);
          }
          await cameraService.disableCamera(id);
          showToast('info', `Camera ${id} hardware disabled`);
          addLog(`Disabled hardware on camera ${id}`, 'warn');
        } else {
          // Enable hardware
          await cameraService.enableCamera(id);
          showToast('success', `Camera ${id} hardware enabled`);
          addLog(`Enabled hardware on camera ${id}`, 'info');
        }
        await refreshCameras();
      } catch (err: any) {
        showToast('error', err?.message || 'Failed to toggle camera hardware state');
      }
    },
    [streamingStates, handleStopStream, showToast, addLog, refreshCameras]
  );

  // ─── 9. Recording Handlers ─────────────────────────────────────────
  const handleToggleRecord = useCallback(
    async (id: number) => {
      const isCurrentlyRecording = recordingStates[id]?.isRecording;
      const cam = cameras.find((c) => c.id === id);

      if (isCurrentlyRecording) {
        // Stop recording
        const sid = recordingStates[id].sessionId;
        try {
          const res = await recordingService.stopRecording(sid, id);
          setRecordingStates((prev) => ({ ...prev, [id]: { isRecording: false, duration: 0, sessionId: '' } }));
          showToast('success', `Recording saved: ${res.filename || 'video file'}`);
          addLog(`Saved recording for Camera ${id}: ${res.recording_path}`, 'info');
        } catch (err: any) {
          showToast('error', err?.message || `Failed to stop recording for Camera ${id}`);
        }
      } else {
        // Start recording
        const sid = `session_${id}_${Date.now()}`;
        try {
          if (!streamingStates[id]) {
            // Auto-activate hardware stream if not active yet
            await cameraService.start({ camera_id: id, ip_address: cam?.ipAddress }).catch(() => {});
            await cameraService.startStream(id).catch(() => {});
            setStreamingStates((prev) => ({ ...prev, [id]: true }));
          }
          const format = cam?.recordingFormat || 'MP4';
          await recordingService.startRecording(sid, format, id);
          setRecordingStates((prev) => ({ ...prev, [id]: { isRecording: true, duration: 0, sessionId: sid } }));
          showToast('info', `Started recording on ${cam?.sourceName || `Camera ${id}`}`);
          addLog(`Started recording on Camera ${id}`, 'info');
        } catch (err: any) {
          showToast('error', err?.message || `Failed to start recording on Camera ${id}`);
        }
      }
    },
    [recordingStates, streamingStates, cameras, showToast, addLog]
  );

  // Dual Record Both: starts/stops recording on all connected & streaming cameras
  const isRecordingBoth =
    cameras.length >= 2 && cameras.every((c) => c.id && recordingStates[c.id]?.isRecording);

  const canRecordBoth =
    cameras.length >= 2 &&
    cameras.filter((c) => c.is_enabled !== false && c.id && streamingStates[c.id]).length >= 2;

  const handleToggleRecordBoth = useCallback(async () => {
    if (isRecordingBoth) {
      // Stop all
      try {
        await recordingService.stopAllRecordings();
        setRecordingStates({});
        showToast('success', 'Synchronized dual recording stopped and saved');
        addLog('Stopped dual recording on all cameras', 'info');
      } catch (err: any) {
        showToast('error', err?.message || 'Failed to stop dual recording');
      }
    } else {
      // Start all
      const baseSid = `dual_session_${Date.now()}`;
      try {
        await recordingService.startAllRecordings(baseSid);
        const newStates: Record<number, { isRecording: boolean; duration: number; sessionId: string }> = {};
        cameras.forEach((c) => {
          if (c.id && streamingStates[c.id]) {
            newStates[c.id] = { isRecording: true, duration: 0, sessionId: `${baseSid}_cam${c.id}` };
          }
        });
        setRecordingStates(newStates);
        showToast('info', 'Synchronized dual recording started on all streaming cameras');
        addLog('Started synchronized dual recording', 'info');
      } catch (err: any) {
        showToast('error', err?.message || 'Failed to start dual recording');
      }
    }
  }, [isRecordingBoth, cameras, streamingStates, showToast, addLog]);

  // ─── 10. Snapshot ──────────────────────────────────────────────────
  const handleSnapshot = useCallback(
    async (id?: number) => {
      const targetId = id || cameras[0]?.id;
      if (!targetId) return;
      try {
        const { blob, filename } = await cameraService.getSnapshot(targetId);
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
        showToast('success', `Snapshot captured: ${filename}`);
        addLog(`Snapshot saved for Camera ${targetId}: ${filename}`, 'info');
      } catch (err: any) {
        showToast('error', err?.message || 'Snapshot capture failed');
      }
    },
    [cameras, showToast, addLog]
  );

  // ─── 11. Edit Camera Save Handler ──────────────────────────────────
  const handleSaveEditedCamera = useCallback(
    async (updated: CameraConfig) => {
      if (!updated.id) return;
      try {
        setConnectionErrors((prev) => ({ ...prev, [updated.id!]: null }));
        await cameraService.updateCamera(updated.id, {
          name: updated.sourceName,
          ip_address: updated.ipAddress,
          resolution: updated.resolution,
          fps: updated.targetFps,
          control_mode: updated.controlMode,
          recording_format: updated.recordingFormat,
          recording_video_path: updated.recordingVideoPath,
        });
        showToast('success', `${updated.sourceName} settings updated`);
        addLog(`Updated camera ${updated.id} parameters in database`, 'info');
        await refreshCameras();
      } catch (err: any) {
        showToast('error', err?.message || 'Failed to update camera');
      }
    },
    [showToast, addLog, refreshCameras]
  );

  const handleDeleteCamera = useCallback(
    async (id: number) => {
      try {
        if (streamingStates[id]) {
          await handleStopStream(id).catch(() => {});
        }
        await cameraService.deleteCamera(id);
        showToast('info', `Camera deleted successfully`);
        addLog(`Deleted camera ${id} from database`, 'warn');
        if (activeControlsCamera?.id === id) setActiveControlsCamera(null);
        if (expandedCameraId === id) setExpandedCameraId(null);
        await refreshCameras();
      } catch (err: any) {
        showToast('error', err?.message || 'Failed to delete camera');
      }
    },
    [streamingStates, handleStopStream, activeControlsCamera, expandedCameraId, showToast, addLog, refreshCameras]
  );

  // ─── 12. Live Controls Updates ─────────────────────────────────────
  const handleUpdateLiveControls = useCallback((id: number, partial: Partial<CameraConfig>) => {
    setCameras((prev) =>
      prev.map((c) => (c.id === id ? { ...c, ...partial } : c))
    );
    setActiveControlsCamera((prev) => (prev?.id === id ? { ...prev, ...partial } : prev));
  }, []);

  // ─── 13. Global Shortcuts ──────────────────────────────────────────
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (['INPUT', 'TEXTAREA', 'SELECT'].includes((e.target as HTMLElement)?.tagName)) {
        return;
      }
      if (e.code === 'Space') {
        e.preventDefault();
        const firstCam = cameras[0];
        if (firstCam?.id) {
          if (streamingStates[firstCam.id]) {
            handleStopStream(firstCam.id);
          } else {
            handleStartStream(firstCam.id);
          }
        }
      } else if (e.key === 's' || e.key === 'S') {
        e.preventDefault();
        handleSnapshot();
      } else if (e.key === 'c' || e.key === 'C') {
        e.preventDefault();
        setActiveControlsCamera((prev) => (prev ? null : cameras[0] || null));
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [cameras, streamingStates, handleStartStream, handleStopStream, handleSnapshot]);

  // ─── 14. Render Landing Screen if Not Initialized ───────────────────
  if (!systemInitialized) {
    return (
      <LandingScreen
        onInitialize={handleInitializeSystem}
        cameraConnected={cameras.some((c) => c.is_enabled)}
      />
    );
  }

  // Stable dual viewports: All configured cameras (up to 2) stay in their permanent slots
  // Disabling hardware turns off the feed in that slot without causing viewports to jump or vanish
  const displayCameras = expandedCameraId !== null
    ? cameras.filter((c) => c.id === expandedCameraId)
    : cameras.slice(0, 2);

  return (
    <div className="flex flex-col h-screen w-screen overflow-hidden bg-[var(--bg-page)] text-[var(--text-primary)] select-none">
      
      {/* Top Header */}
      <Header
        theme={theme}
        onThemeChange={handleThemeChange}
        cameraConfig={cameras[0]}
        activeCameraCount={cameras.filter((c) => c.is_enabled !== false).length}
        canRecordBoth={canRecordBoth}
        isRecordingBoth={isRecordingBoth}
        onToggleRecordBoth={handleToggleRecordBoth}
        onAddCamera={() => setAddCameraOpen(true)}
        onOpenSettings={() => setAddCameraOpen(true)}
        onOpenHelp={() => setHelpOpen(true)}
        onExitToLanding={() => setSystemInitialized(false)}
      />

      {/* Main Workspace Body */}
      <main className="flex-1 flex overflow-hidden p-2 sm:p-3 gap-2 sm:gap-3">
        
        {/* Left / Center: Cameras Canvas Viewports */}
        <div className="flex-1 flex flex-col h-full min-w-0">
          
          {cameras.length === 0 ? (
            /* Standby view when no cameras exist yet */
            <div className="flex-1 flex flex-col items-center justify-center p-8 rounded-2xl bg-[var(--bg-card)] border border-[var(--border-color)] text-center">
              <div className="w-16 h-16 rounded-2xl bg-[var(--accent-pond-subtle)] text-[var(--accent-pond)] flex items-center justify-center mb-4">
                <Camera className="w-8 h-8" />
              </div>
              <h2 className="text-lg sm:text-xl font-bold text-[var(--text-primary)] mb-2">
                No Cameras Configured
              </h2>
              <p className="text-xs sm:text-sm text-[var(--text-secondary)] max-w-md mb-6 leading-relaxed">
                Add your first USB or IP/PoE camera to begin live streaming, tuning, and synchronized recording.
              </p>
              <button
                onClick={() => setAddCameraOpen(true)}
                className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-[var(--btn-primary-bg)] text-[var(--btn-primary-text)] font-bold text-xs sm:text-sm shadow-md hover:opacity-90 active:scale-95 transition-all cursor-pointer"
              >
                <Plus className="w-4 h-4 stroke-[2.5]" />
                <span>Add First Camera</span>
              </button>
            </div>
          ) : (
            /* Active Cameras Grid: Single Card per Camera (Side-by-Side 50/50 or Expanded) */
            <div
              className={`grid h-full gap-2 sm:gap-3 ${
                expandedCameraId !== null || displayCameras.length === 1
                  ? 'grid-cols-1'
                  : 'grid-cols-1 md:grid-cols-2'
              }`}
            >
              {displayCameras.map((cam, idx) => {
                const camId = cam.id || idx + 1;
                return (
                  <CameraCard
                    key={camId}
                    camera={cam}
                    index={idx + 1}
                    isStreaming={Boolean(streamingStates[camId])}
                    isStarting={Boolean(startingStates[camId])}
                    isRecording={Boolean(recordingStates[camId]?.isRecording)}
                    recordingDuration={recordingStates[camId]?.duration || 0}
                    isExpanded={expandedCameraId === camId}
                    isControlsOpen={activeControlsCamera?.id === camId}
                    connectionError={connectionErrors[camId] || null}
                    onStartStream={handleStartStream}
                    onStopStream={handleStopStream}
                    onToggleRecord={handleToggleRecord}
                    onToggleEnable={handleToggleEnable}
                    onExpandToggle={(id) => setExpandedCameraId((prev) => (prev === id ? null : id))}
                    onOpenEdit={(c) => setEditCamera(c)}
                    onOpenControls={(c) =>
                      setActiveControlsCamera((prev) => (prev?.id === c.id ? null : c))
                    }
                    onSnapshot={handleSnapshot}
                  />
                );
              })}
            </div>
          )}

        </div>

        {/* Right Drawer: Live Camera Image Adjustments Panel */}
        {activeControlsCamera && (
          <aside className="w-80 lg:w-96 flex-shrink-0 animate-in slide-in-from-right-4 duration-200 overflow-y-auto">
            <CameraImageAdjustmentsCard
              cameraId={activeControlsCamera.id}
              config={activeControlsCamera}
              onUpdateConfig={(partial) => {
                if (activeControlsCamera.id) {
                  handleUpdateLiveControls(activeControlsCamera.id, partial);
                }
              }}
              isLive={Boolean(activeControlsCamera.id && streamingStates[activeControlsCamera.id])}
              onClose={() => setActiveControlsCamera(null)}
            />
          </aside>
        )}

      </main>

      {/* Add Camera Modal (Existing tested setup fields) */}
      <CameraSettingsModal
        isOpen={addCameraOpen}
        onClose={() => {
          setAddCameraOpen(false);
          refreshCameras();
        }}
        config={cameras[0] || {
          sourceName: 'Camera 1',
          resolution: '1920x1080',
          targetFps: 30,
          exposure: 8,
          gain: 400,
          iso: 400,
          brightness: 0,
          contrast: 50,
          autoFocus: false,
          connected: false,
          ipAddress: '',
        }}
        onSaveConfig={async () => {
          await refreshCameras();
          setAddCameraOpen(false);
        }}
        onReconnect={async (updatedCamera?: CameraConfig) => {
          await refreshCameras();
          setAddCameraOpen(false);
          const cid = updatedCamera?.id || 1;
          setTimeout(() => {
            handleStartStream(cid).catch(() => {});
          }, 300);
        }}
      />

      {/* Edit Camera Modal (Per-camera parameters) */}
      <CameraEditModal
        isOpen={Boolean(editCamera)}
        onClose={() => setEditCamera(null)}
        camera={editCamera}
        onSave={handleSaveEditedCamera}
        onDelete={handleDeleteCamera}
      />

      {/* Help Modal */}
      <HelpModal
        isOpen={helpOpen}
        onClose={() => setHelpOpen(false)}
      />

      {/* Toast Notification Container */}
      {toast && (
        <Toast
          type={toast.type}
          message={toast.message}
          onClose={() => setToast(null)}
        />
      )}

    </div>
  );
}
