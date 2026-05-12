export const SETTINGS_UPDATED_EVENT = "life-assistant-settings-updated";

export function notifySettingsUpdated(): void {
  if (typeof document === "undefined" || typeof CustomEvent === "undefined") {
    return;
  }

  document.dispatchEvent(new CustomEvent(SETTINGS_UPDATED_EVENT));
}
