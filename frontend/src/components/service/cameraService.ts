import { api } from "../../lib/api";

export interface CameraData {
  id?: number;
  name?: string;
  ip_address?: string;
  resolution?: string;
  fps?: number;
  rotation_angle?: number;
  control_mode?: 'auto' | 'manual';
  exposure?: number;
  gain?: number;
  focus?: number;
  brightness?: number;
  contrast?: number;
  auto_focus?: boolean;
  auto_exposure?: boolean;
  is_enabled?: boolean;
  recording_format?: string;
  recording_video_path?: string | null;
  clip_duration_minutes?: number;
}

export const cameraService = {
  async checkCamera() {
    const res = await api.get("/camera/");
    return res.data;
  },

  async createCamera(data: CameraData) {
    const res = await api.post("/camera/create", data);
    return res.data;
  },

  async enableCamera(id: string | number) {
    const res = await api.post(`/camera/enable/${id}`);
    return res.data;
  },

  async disableCamera(id: string | number) {
    const res = await api.post(`/camera/disable/${id}`);
    return res.data;
  },

  async updateCamera(id: string | number, data: CameraData) {
    const res = await api.put(`/camera/update/${id}`, data);
    return res.data;
  },

  async deleteCamera(id: string | number) {
    const res = await api.delete(`/camera/${id}`);
    return res.data;
  },

  async saveCamera(data: CameraData) {
    if (data.id) {
      return await this.updateCamera(data.id, data);
    }
    return await this.createCamera(data);
  },

  async start(payload?: { camera_id?: number; ip_address?: string }) {
    const res = await api.post("/oak/start", payload || {});
    if (res.data?.status === 'error') {
      throw new Error(res.data.message || 'Camera start failed');
    }
    return res.data;
  },

  async stop(cameraId?: number | string) {
    const cid = cameraId ? parseInt(String(cameraId), 10) : undefined;
    const res = await api.post("/oak/stop", { camera_id: cid });
    return res.data;
  },

  async startStream(cameraId?: number | string) {
    const cid = cameraId ? parseInt(String(cameraId), 10) : undefined;
    const res = await api.post("/oak/stream/start", { camera_id: cid });
    return res.data;
  },

  async stopStream(cameraId?: number | string) {
    const cid = cameraId ? parseInt(String(cameraId), 10) : undefined;
    const res = await api.post("/oak/stream/stop", { camera_id: cid });
    return res.data;
  },

  getStreamUrl(cameraId?: number | string) {
    const baseUrl = api.defaults.baseURL || 'http://127.0.0.1:8000';
    if (cameraId) {
      return `${baseUrl}/oak/stream/${cameraId}`;
    }
    return `${baseUrl}/oak/stream`;
  },

  async getSnapshot(cameraId?: number | string): Promise<{ blob: Blob; filename: string }> {
    const url = cameraId ? `/oak/snapshot/${cameraId}` : '/oak/snapshot';
    const res = await api.get(url, { responseType: 'blob' });
    const filename = `snapshot_${cameraId ? `cam${cameraId}_` : ''}${new Date().toISOString().replace(/[:.]/g, '-')}.jpg`;
    return { blob: res.data, filename };
  },

  async health() {
    const res = await api.get("/oak/health");
    return res.data;
  },

  async updateLiveControls(id: string | number | undefined, data: any) {
    if (id) {
      try {
        const res = await api.patch(`/camera/live-controls/${id}`, data);
        return res.data;
      } catch (err) {
        console.warn(`[cameraService] PATCH /camera/live-controls/${id} failed, trying /oak/controls:`, err);
      }
    }
    const res = await api.post("/oak/controls", data);
    return res.data;
  },

  async resetCameraControls() {
    try {
      const res = await api.post("/oak/controls/reset");
      return res.data;
    } catch {
      const res = await api.post("/oak/controls", { reset: true, auto_exposure: false, auto_focus: false, brightness: 0, contrast: 0 });
      return res.data;
    }
  },

  async recalibrateControls() {
    const res = await api.post("/oak/controls/calibrate");
    return res.data;
  },

  async saveLiveControls() {
    const res = await api.post("/oak/controls/save");
    return res.data;
  },

  async getAvailableDevices() {
    try {
      const res = await api.get("/oak/devices");
      return res.data || [];
    } catch {
      return [];
    }
  },

  async getStoragePath(): Promise<{ storage_path: string; default_path: string }> {
    const res = await api.get("/camera/storage-path");
    return res.data;
  },

  async getCameraLimits(id: string | number) {
    try {
      const res = await api.get(`/camera/limits/${id}`);
      return res.data;
    } catch (err) {
      console.warn(`[cameraService] getCameraLimits failed for ${id}:`, err);
      return null;
    }
  },

  async setStoragePath(path: string | null): Promise<{ storage_path: string; default_path: string }> {
    const res = await api.post("/camera/storage-path", { path });
    return res.data;
  },

  async browseFolder(initialDir?: string): Promise<{ path: string | null; canceled: boolean }> {
    const res = await api.post("/camera/browse-folder", { initial_dir: initialDir });
    return res.data;
  },
};

export default cameraService;
