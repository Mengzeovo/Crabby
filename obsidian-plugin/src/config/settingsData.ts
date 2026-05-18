import { resolve } from "node:path";

import type { CrabbySettings, LlmProfile } from "../settings";
import { normalizeLlmProviderId } from "./llmProviders";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function normalizeString(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value.trim() : fallback;
}

function normalizeProfileId(value: unknown, fallback = ""): string {
  return normalizeString(value, fallback)
    .replace(/[^A-Za-z0-9_]/g, "_")
    .slice(0, 64);
}

function normalizeProvider(value: unknown): LlmProfile["provider"] {
  return normalizeLlmProviderId(value);
}

function normalizeBoolean(value: unknown): boolean {
  if (typeof value === "boolean") {
    return value;
  }

  if (typeof value === "string") {
    const normalized = value.trim().toLowerCase();
    if (["1", "true", "yes", "on"].includes(normalized)) {
      return true;
    }
    if (["0", "false", "no", "off", ""].includes(normalized)) {
      return false;
    }
  }

  if (typeof value === "number") {
    return value !== 0;
  }

  return false;
}

function normalizeProfile(profile: unknown): LlmProfile | null {
  if (!isRecord(profile)) {
    return null;
  }

  const id = normalizeProfileId(profile.id);
  const name = normalizeString(profile.name);
  const model = normalizeString(profile.model);

  if (!id || !name || !model) {
    return null;
  }

  return {
    id,
    name,
    provider: normalizeProvider(profile.provider),
    model,
    baseUrl: normalizeString(profile.baseUrl),
    apiKey: normalizeString(profile.apiKey),
    supportsVision: normalizeBoolean(profile.supportsVision),
    thinkingMode: normalizeString(profile.thinkingMode),
    thinkingEffort: normalizeString(profile.thinkingEffort),
    thinkingBudgetTokens: normalizeString(profile.thinkingBudgetTokens, "1024"),
    reasoningSplit: normalizeBoolean(profile.reasoningSplit),
    isDraft: normalizeBoolean(profile.isDraft),
  };
}

function normalizeBackendEnvPath(
  source: Record<string, unknown>,
  defaults: CrabbySettings,
): string {
  const backendEnvPath = normalizeString(
    source.backendEnvPath,
    defaults.backendEnvPath,
  );
  if (backendEnvPath) {
    return resolve(backendEnvPath);
  }

  const legacyBackendPath = normalizeString(source.backendPath);
  if (legacyBackendPath) {
    return resolve(legacyBackendPath, ".env");
  }

  return "";
}

export function needsBackendEnvPathMigration(loaded: unknown): boolean {
  if (!isRecord(loaded)) {
    return false;
  }

  return !normalizeString(loaded.backendEnvPath) && !!normalizeString(loaded.backendPath);
}

export function hydrateSettings(
  defaults: CrabbySettings,
  loaded: unknown,
): CrabbySettings {
  const source = isRecord(loaded) ? loaded : {};
  const backendEnvPath = normalizeBackendEnvPath(source, defaults);

  return {
    ...defaults,
    backendUrl: normalizeString(source.backendUrl, defaults.backendUrl),
    backendEnvPath,
    backendMcpConfigPath: normalizeString(
      source.backendMcpConfigPath,
      defaults.backendMcpConfigPath,
    ),
    runtimeManifestUrl: normalizeString(
      source.runtimeManifestUrl,
      defaults.runtimeManifestUrl,
    ),
    backendPath: "",
    llmProfiles: Array.isArray(source.llmProfiles)
      ? source.llmProfiles
          .map((profile) => normalizeProfile(profile))
          .filter((profile): profile is LlmProfile => profile !== null)
      : defaults.llmProfiles.map((profile) => ({ ...profile })),
    activeProfileId: normalizeProfileId(
      source.activeProfileId,
      defaults.activeProfileId,
    ),
  };
}
