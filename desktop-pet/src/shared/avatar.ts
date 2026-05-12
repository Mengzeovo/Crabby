import {
  CRABBY_AVATAR_ASSET,
  DEFAULT_AVATAR_ASSET,
} from "./constants";
import type { BubbleState, ConnectionState } from "./types";

export type CrabbyAvatarVariant =
  | "normal"
  | "happy"
  | "thinking"
  | "error"
  | "idle";

export interface AvatarRenderState {
  isStreaming: boolean;
  unreadCount: number;
  connectionState: ConnectionState;
  bubble: BubbleState;
}

export function isBuiltinCrabbyAsset(asset?: string): boolean {
  const normalized = asset?.trim() || "";
  return (
    normalized === CRABBY_AVATAR_ASSET ||
    normalized.startsWith(`${CRABBY_AVATAR_ASSET}:`)
  );
}

export function createBuiltinCrabbyAsset(
  variant: CrabbyAvatarVariant,
): string {
  return `${CRABBY_AVATAR_ASSET}:${variant}`;
}

export function getDynamicAvatarAsset(
  asset: string | undefined,
  snapshot: AvatarRenderState | null,
): string {
  const normalized = asset?.trim() || DEFAULT_AVATAR_ASSET;
  if (!snapshot || !isBuiltinCrabbyAsset(normalized)) {
    return normalized;
  }

  if (snapshot.connectionState === "error") {
    return createBuiltinCrabbyAsset("error");
  }

  if (snapshot.isStreaming || snapshot.connectionState === "connecting") {
    return createBuiltinCrabbyAsset("thinking");
  }

  if (snapshot.unreadCount > 0 || snapshot.bubble.visible) {
    return createBuiltinCrabbyAsset("happy");
  }

  if (snapshot.connectionState === "connected") {
    return createBuiltinCrabbyAsset("normal");
  }

  return createBuiltinCrabbyAsset("idle");
}
