const KEY = 'vision_monitor_session_state';

export interface PersistedSessionState {
  isStreaming?: boolean;
}

export function saveSessionState(state: Partial<PersistedSessionState>) {
  try {
    const existing = loadSessionState() ?? ({} as PersistedSessionState);
    const merged: any = { ...existing, ...state };
    for (const k of Object.keys(merged)) {
      if (merged[k] === undefined || merged[k] === null || merged[k] === '') {
        delete merged[k];
      }
    }
    if (Object.keys(merged).length === 0) {
      sessionStorage.removeItem(KEY);
    } else {
      sessionStorage.setItem(KEY, JSON.stringify(merged));
    }
  } catch {
    // sessionStorage quota exceeded or other error
  }
}

export function loadSessionState(): PersistedSessionState | null {
  try {
    const raw = sessionStorage.getItem(KEY);
    if (!raw) return null;
    return JSON.parse(raw) as PersistedSessionState;
  } catch {
    return null;
  }
}

export function clearSessionState() {
  try {
    sessionStorage.removeItem(KEY);
  } catch { }
}
