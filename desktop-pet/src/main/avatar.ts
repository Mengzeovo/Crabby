import path from "node:path";

import {
  CLASSIC_AVATAR_ASSET,
  CRABBY_AVATAR_ASSET,
  DEFAULT_AVATAR_ASSET,
  LEGACY_AVATAR_ASSET,
} from "../shared/constants";

const builtinAvatarAssetMap = new Map<string, string>([
  [LEGACY_AVATAR_ASSET, path.join("assets", "pet.svg")],
  [CLASSIC_AVATAR_ASSET, path.join("assets", "pet.svg")],
  [
    CRABBY_AVATAR_ASSET,
    path.join("assets", "Crabby", "face_normal_fullbody_transparent.png"),
  ],
  [
    `${CRABBY_AVATAR_ASSET}:normal`,
    path.join("assets", "Crabby", "face_normal_fullbody_transparent.png"),
  ],
  [
    `${CRABBY_AVATAR_ASSET}:happy`,
    path.join("assets", "Crabby", "face_happy_fullbody_transparent.png"),
  ],
  [
    `${CRABBY_AVATAR_ASSET}:thinking`,
    path.join("assets", "Crabby", "thinking_fullbody_transparent.png"),
  ],
  [
    `${CRABBY_AVATAR_ASSET}:error`,
    path.join("assets", "Crabby", "reconnect_error_fullbody_transparent.png"),
  ],
  [
    `${CRABBY_AVATAR_ASSET}:idle`,
    path.join("assets", "Crabby", "offline_fullbody_transparent.png"),
  ],
]);

export function resolveAvatarAssetUrl(distRoot: string, asset: string): string {
  const normalized = asset.trim() || DEFAULT_AVATAR_ASSET;

  const builtinAssetPath = builtinAvatarAssetMap.get(normalized);
  if (builtinAssetPath) {
    return `file://${path.join(distRoot, builtinAssetPath).replace(/\\/g, "/")}`;
  }

  if (
    normalized.startsWith("file://") ||
    normalized.startsWith("http://") ||
    normalized.startsWith("https://")
  ) {
    return normalized;
  }

  return `file://${normalized.replace(/\\/g, "/")}`;
}
