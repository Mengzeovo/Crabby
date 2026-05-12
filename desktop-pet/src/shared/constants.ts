import type { BubbleState, ConversationSnapshot, PetSettings } from "./types";

export const DEFAULT_BACKEND_URL = "http://127.0.0.1:8000";
export const LEGACY_AVATAR_ASSET = "builtin:pet";
export const CLASSIC_AVATAR_ASSET = "builtin:pet:legacy";
export const CRABBY_AVATAR_ASSET = "builtin:crabby";
export const DEFAULT_AVATAR_ASSET = CRABBY_AVATAR_ASSET;
export const DEFAULT_PET_SCALE = 1;

export const DEFAULT_SETTINGS: PetSettings = {
  backendUrl: DEFAULT_BACKEND_URL,
  launchOnLogin: false,
  alwaysOnTop: true,
  petPosition: null,
  petScale: DEFAULT_PET_SCALE,
  avatarAsset: DEFAULT_AVATAR_ASSET,
  showDockIcon: false,
  primaryConversationId: "",
};

export const EMPTY_BUBBLE: BubbleState = {
  visible: false,
  message: "",
  autoTrigger: false,
};

export const AUTO_TRIGGER_MESSAGE =
  "(System notification: the background task just finished. Please continue the reply using the newly injected <task_notification> context.)";

export function createEmptySnapshot(conversationId: string): ConversationSnapshot {
  return {
    conversationId,
    activeConversationId: "",
    title: "New chat",
    entries: [],
    isStreaming: false,
    unreadCount: 0,
    connectionState: "disconnected",
    lastError: null,
    bubble: EMPTY_BUBBLE,
    lastContext: null,
  };
}
