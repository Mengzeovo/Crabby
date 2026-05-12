import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";

import {
  DEFAULT_AVATAR_ASSET,
  DEFAULT_SETTINGS,
  LEGACY_AVATAR_ASSET,
} from "../shared/constants";
import type { PetSettings } from "../shared/types";

export function normalizeSettings(raw: Partial<PetSettings> | null | undefined): PetSettings {
  const merged: PetSettings = {
    ...DEFAULT_SETTINGS,
    ...(raw ?? {}),
  };

  if (!Number.isFinite(merged.petScale)) {
    merged.petScale = DEFAULT_SETTINGS.petScale;
  }
  merged.petScale = Math.min(1.4, Math.max(0.75, merged.petScale));

  if (
    merged.petPosition &&
    (!Number.isFinite(merged.petPosition.x) || !Number.isFinite(merged.petPosition.y))
  ) {
    merged.petPosition = null;
  }

  merged.backendUrl = merged.backendUrl?.trim() || DEFAULT_SETTINGS.backendUrl;
  merged.avatarAsset = (merged.avatarAsset || DEFAULT_SETTINGS.avatarAsset).trim();
  if (merged.avatarAsset === LEGACY_AVATAR_ASSET) {
    merged.avatarAsset = DEFAULT_AVATAR_ASSET;
  }
  merged.primaryConversationId = (merged.primaryConversationId || "").trim();

  return merged;
}

export async function loadSettingsFromFile(filePath: string): Promise<PetSettings> {
  try {
    const raw = await readFile(filePath, "utf8");
    return normalizeSettings(JSON.parse(raw) as Partial<PetSettings>);
  } catch {
    return { ...DEFAULT_SETTINGS };
  }
}

export async function saveSettingsToFile(
  filePath: string,
  settings: PetSettings,
): Promise<void> {
  await mkdir(path.dirname(filePath), { recursive: true });
  await writeFile(
    filePath,
    `${JSON.stringify(normalizeSettings(settings), null, 2)}\n`,
    "utf8",
  );
}

export class SettingsStore {
  constructor(private readonly filePath: string) {}

  async load(): Promise<PetSettings> {
    return loadSettingsFromFile(this.filePath);
  }

  async save(settings: PetSettings): Promise<void> {
    await saveSettingsToFile(this.filePath, settings);
  }
}
