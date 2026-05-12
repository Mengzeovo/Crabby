import path from "node:path";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";

import { describe, expect, it } from "vitest";

import {
  DEFAULT_SETTINGS,
  LEGACY_AVATAR_ASSET,
} from "../src/shared/constants";
import {
  loadSettingsFromFile,
  normalizeSettings,
  saveSettingsToFile,
} from "../src/main/settingsStore";

describe("settingsStore", () => {
  it("normalizes invalid values back to safe defaults", () => {
    const normalized = normalizeSettings({
      backendUrl: "   ",
      petScale: 99,
      petPosition: { x: Number.NaN, y: 10 },
      avatarAsset: "",
      primaryConversationId: "   ",
    });

    expect(normalized.backendUrl).toBe(DEFAULT_SETTINGS.backendUrl);
    expect(normalized.petScale).toBe(1.4);
    expect(normalized.petPosition).toBeNull();
    expect(normalized.avatarAsset).toBe(DEFAULT_SETTINGS.avatarAsset);
    expect(normalized.primaryConversationId).toBe("");
  });

  it("migrates the legacy builtin avatar token to the crabby pack", () => {
    const normalized = normalizeSettings({
      avatarAsset: LEGACY_AVATAR_ASSET,
    });

    expect(normalized.avatarAsset).toBe(DEFAULT_SETTINGS.avatarAsset);
  });

  it("persists normalized settings to disk", async () => {
    const tempDir = await mkdtemp(path.join(tmpdir(), "pet-settings-"));
    const filePath = path.join(tempDir, "settings.json");

    await saveSettingsToFile(filePath, {
      ...DEFAULT_SETTINGS,
      petScale: 2,
    });

    const raw = await readFile(filePath, "utf8");
    const reloaded = await loadSettingsFromFile(filePath);

    expect(raw).toContain('"petScale": 1.4');
    expect(reloaded.petScale).toBe(1.4);

    await rm(tempDir, { recursive: true, force: true });
  });
});
