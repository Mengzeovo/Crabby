import { DEFAULT_AVATAR_ASSET } from "../shared/constants";
import { getDynamicAvatarAsset } from "../shared/avatar";
import type { ConversationSnapshot, PetSettings } from "../shared/types";

const petButton = document.getElementById("petButton") as HTMLButtonElement;
const petAvatar = document.getElementById("petAvatar") as HTMLImageElement;
const petState = document.getElementById("petState") as HTMLSpanElement;
const petUnread = document.getElementById("petUnread") as HTMLSpanElement;

let currentSettings: PetSettings | null = null;
let currentSnapshot: ConversationSnapshot | null = null;
let pointerStart: { x: number; y: number } | null = null;
let dragging = false;
let currentAvatarAsset = "";

function formatState(snapshot: ConversationSnapshot): string {
  if (snapshot.isStreaming) {
    return "Thinking";
  }
  switch (snapshot.connectionState) {
    case "connected":
      return "Ready";
    case "connecting":
      return "Connecting";
    case "error":
      return "Reconnect";
    default:
      return "Offline";
  }
}

async function refreshAvatar(asset?: string): Promise<void> {
  const nextAsset = asset?.trim() || DEFAULT_AVATAR_ASSET;
  if (currentAvatarAsset === nextAsset) {
    return;
  }
  currentAvatarAsset = nextAsset;
  petAvatar.src = await window.desktopPet.resolveAvatarUrl(nextAsset);
}

function getDisplayedAvatarAsset(): string {
  return getDynamicAvatarAsset(
    currentSettings?.avatarAsset,
    currentSnapshot,
  );
}

function renderSnapshot(snapshot: ConversationSnapshot): void {
  currentSnapshot = snapshot;
  petState.textContent = formatState(snapshot);
  if (snapshot.unreadCount > 0) {
    petUnread.hidden = false;
    petUnread.textContent = String(Math.min(snapshot.unreadCount, 99));
  } else {
    petUnread.hidden = true;
  }

  void refreshAvatar(getDisplayedAvatarAsset());
}

function cleanupPointerListeners(): void {
  window.removeEventListener("pointermove", handlePointerMove);
  window.removeEventListener("pointerup", handlePointerUp);
  window.removeEventListener("pointercancel", handlePointerUp);
}

async function handlePointerMove(event: PointerEvent): Promise<void> {
  if (!pointerStart) {
    return;
  }
  const distance = Math.hypot(event.screenX - pointerStart.x, event.screenY - pointerStart.y);
  if (!dragging && distance > 6) {
    dragging = true;
    await window.desktopPet.beginPetDrag(pointerStart);
  }

  if (dragging) {
    await window.desktopPet.updatePetDrag({ x: event.screenX, y: event.screenY });
  }
}

async function handlePointerUp(event: PointerEvent): Promise<void> {
  cleanupPointerListeners();
  if (!pointerStart) {
    return;
  }

  if (dragging) {
    await window.desktopPet.endPetDrag({ x: event.screenX, y: event.screenY });
  } else {
    await window.desktopPet.notifyPetClick();
  }

  pointerStart = null;
  dragging = false;
}

petButton.addEventListener("pointerdown", (event) => {
  pointerStart = { x: event.screenX, y: event.screenY };
  dragging = false;
  window.addEventListener("pointermove", handlePointerMove);
  window.addEventListener("pointerup", handlePointerUp);
  window.addEventListener("pointercancel", handlePointerUp);
});

window.desktopPet.subscribeConversationSnapshot(renderSnapshot);
window.desktopPet.subscribeSettings((settings) => {
  currentSettings = settings;
  void refreshAvatar(getDisplayedAvatarAsset());
});

void (async () => {
  const [settings, snapshot] = await Promise.all([
    window.desktopPet.getSettings(),
    window.desktopPet.getConversationSnapshot(),
  ]);
  currentSettings = settings;
  renderSnapshot(snapshot);
})();
