import { contextBridge, ipcRenderer } from "electron";

import type { ElectronDesktopApi } from "../shared/types";

const api: ElectronDesktopApi = {
  getEnvironment: () => ipcRenderer.invoke("desktop:get-environment"),
  getConversationSnapshot: () => ipcRenderer.invoke("conversation:get-snapshot"),
  subscribeConversationSnapshot: (callback) => {
    const listener = (_event: Electron.IpcRendererEvent, payload: unknown) => {
      callback(payload as Parameters<typeof callback>[0]);
    };
    ipcRenderer.on("conversation:snapshot", listener);
    return () => {
      ipcRenderer.off("conversation:snapshot", listener);
    };
  },
  sendChatMessage: (content) => ipcRenderer.invoke("conversation:send-message", content),
  abortChat: () => ipcRenderer.invoke("conversation:abort"),
  openChatWindow: () => ipcRenderer.invoke("window:open-chat"),
  openSettingsWindow: () => ipcRenderer.invoke("window:open-settings"),
  dismissBubble: () => ipcRenderer.invoke("bubble:dismiss"),
  getSettings: () => ipcRenderer.invoke("settings:get"),
  updateSettings: (next) => ipcRenderer.invoke("settings:update", next),
  subscribeSettings: (callback) => {
    const listener = (_event: Electron.IpcRendererEvent, payload: unknown) => {
      callback(payload as Parameters<typeof callback>[0]);
    };
    ipcRenderer.on("settings:updated", listener);
    return () => {
      ipcRenderer.off("settings:updated", listener);
    };
  },
  resolveAvatarUrl: (asset) => ipcRenderer.invoke("avatar:resolve", asset),
  beginPetDrag: (payload) => ipcRenderer.invoke("pet:drag-begin", payload),
  updatePetDrag: (payload) => ipcRenderer.invoke("pet:drag-update", payload),
  endPetDrag: (payload) => ipcRenderer.invoke("pet:drag-end", payload),
  notifyPetClick: () => ipcRenderer.invoke("pet:click"),
  markChatSeen: () => ipcRenderer.invoke("conversation:mark-seen"),
};

contextBridge.exposeInMainWorld("desktopPet", api);
