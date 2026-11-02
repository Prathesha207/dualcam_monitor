import { useState, useRef, useCallback, useEffect } from 'react';
import { recordingService, StopRecordingResponse } from '../service/recordingService';
import { showToast } from '../../lib/toast';

export function useRecording() {
  const [isRecording, setIsRecording] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [recordingDuration, setRecordingDuration] = useState(0);
  const [recordedVideoUrl, setRecordedVideoUrl] = useState<string | null>(null);
  const [recordedFile, setRecordedFile] = useState<File | null>(null);

  const sessionIdRef = useRef<string | null>(null);
  const durationIntervalRef = useRef<NodeJS.Timeout | null>(null);
  const startTimeRef = useRef<number | null>(null);

  useEffect(() => {
    return () => {
      if (durationIntervalRef.current) {
        clearInterval(durationIntervalRef.current);
      }
    };
  }, []);

  const startRecording = useCallback(async (recordingFormat: string = 'MP4') => {
    if (isRecording || isSaving) return false;

    const newSessionId = `rec_${Date.now()}`;
    sessionIdRef.current = newSessionId;

    try {
      const res = await recordingService.startRecording(newSessionId, recordingFormat);
      if (res && res.status === 'recording') {
        setIsRecording(true);
        setRecordingDuration(0);
        startTimeRef.current = Date.now();
        if (durationIntervalRef.current) clearInterval(durationIntervalRef.current);
        durationIntervalRef.current = setInterval(() => {
          if (startTimeRef.current) {
            setRecordingDuration(Math.floor((Date.now() - startTimeRef.current) / 1000));
          }
        }, 1000);
        return true;
      } else {
        showToast('error', 'Failed to start camera recording on backend.');
        return false;
      }
    } catch (err: any) {
      console.error('[RECORD] startRecording error:', err);
      showToast('error', err?.message || 'Failed to start recording');
      return false;
    }
  }, [isRecording, isSaving]);

  const stopRecording = useCallback(async () => {
    if (!isRecording || isSaving) return null;

    setIsSaving(true);
    if (durationIntervalRef.current) {
      clearInterval(durationIntervalRef.current);
      durationIntervalRef.current = null;
    }

    try {
      const activeSessionId = sessionIdRef.current || `rec_${Date.now()}`;
      const res = await recordingService.stopRecording(activeSessionId);

      setIsRecording(false);
      setIsSaving(false);
      sessionIdRef.current = null;
      startTimeRef.current = null;

      if (res && res.status === 'stopped') {
        if (res.recording_path) {
          setRecordedVideoUrl(res.recording_path);
        }
        showToast('success', `Recording saved: ${res.filename || 'camera_recording.mp4'}`);
        return res;
      } else {
        showToast('error', res?.message || 'Failed to stop recording cleanly.');
        return null;
      }
    } catch (err: any) {
      console.error('[RECORD] stopRecording error:', err);
      setIsRecording(false);
      setIsSaving(false);
      showToast('error', err?.message || 'Failed to stop recording');
      return null;
    }
  }, [isRecording, isSaving]);

  const clearRecording = useCallback(() => {
    setRecordedVideoUrl(null);
    setRecordedFile(null);
    setRecordingDuration(0);
  }, []);

  return {
    isRecording,
    isSaving,
    recordingDuration,
    recordedVideoUrl,
    recordedFile,
    startRecording,
    stopRecording,
    clearRecording,
  };
}
