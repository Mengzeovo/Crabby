import type { ElectronDesktopApi } from "./types";

declare global {
  interface Window {
    desktopPet: ElectronDesktopApi;
  }
}

export {};
