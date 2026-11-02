const { contextBridge, ipcRenderer } = require("electron")

contextBridge.exposeInMainWorld("electronAPI", {
  selectFolder: () => ipcRenderer.invoke("select-folder"),
  selectFile: () => ipcRenderer.invoke("select-file"),
  writeLog: (message) => ipcRenderer.invoke("write-log", message),
  // Notify main process about recording state for the close guard dialog
  setRecordingActive: (active) => ipcRenderer.send("set-recording-active", active),
  setInferenceRunning: (running) => ipcRenderer.send("set-inference-running", running),
})
