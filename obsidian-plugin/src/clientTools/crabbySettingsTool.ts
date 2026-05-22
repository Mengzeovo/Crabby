import { existsSync } from "node:fs";
import { join, resolve } from "node:path";

import { AgentClient } from "../api/client";
import {
  activateLlmProfileOnBackend,
  deleteLlmProfileFromBackend,
  fetchLlmProfilesFromBackend,
  saveLlmProfileToBackend,
} from "../config/backendConfig";
import { resolveDiaryConfigPath } from "../config/diaryConfig";
import { normalizeLlmProviderId } from "../config/llmProviders";
import { resolvePluginRuntimeLayout } from "../runtime/backendRuntime";
import type CrabbyPlugin from "../main";
import type { LlmProfile } from "../settings";

export type CrabbySettingsToolAction =
  | "inspect"
  | "set_runtime_value"
  | "save_profile"
  | "delete_profile"
  | "activate_profile"
  | "sync_profiles_from_backend"
  | "sync_backend_vault_path";

export interface CrabbySettingsToolInput {
  action: CrabbySettingsToolAction;
  key?: string;
  value?: string;
  profile_id?: string;
  profile?: unknown;
  activate?: boolean;
}

interface CrabbySettingsToolResult {
  ok: boolean;
  message: string;
  settings?: Record<string, unknown>;
  changed?: string[];
}

const RUNTIME_KEYS = new Set([
  "backendUrl",
  "backendEnvPath",
  "backendMcpConfigPath",
  "runtimeManifestUrl",
]);

export async function performCrabbySettingsAction(
  plugin: CrabbyPlugin,
  input: CrabbySettingsToolInput,
): Promise<CrabbySettingsToolResult> {
  switch (input.action) {
    case "inspect":
      return {
        ok: true,
        message: "Loaded current Crabby plugin settings.",
        settings: buildSettingsSnapshot(plugin),
      };
    case "set_runtime_value":
      return await setRuntimeValue(plugin, input);
    case "save_profile":
      return await saveProfile(plugin, input);
    case "delete_profile":
      return await deleteProfile(plugin, input);
    case "activate_profile":
      return await activateProfile(plugin, input);
    case "sync_profiles_from_backend":
      return await syncProfilesFromBackend(plugin);
    case "sync_backend_vault_path":
      return await syncBackendVaultPath(plugin);
    default:
      return {
        ok: false,
        message: `Unknown crabby_settings action: ${String(input.action ?? "")}`,
        settings: buildSettingsSnapshot(plugin),
      };
  }
}

export function normalizeCrabbySettingsInput(
  input: unknown,
): CrabbySettingsToolInput {
  if (!input || typeof input !== "object") {
    return { action: "inspect" };
  }
  const record = input as Record<string, unknown>;
  return {
    action: normalizeAction(record.action),
    key: normalizeString(record.key),
    value: normalizeString(record.value),
    profile_id: normalizeString(record.profile_id),
    profile: record.profile,
    activate: Boolean(record.activate),
  };
}

function normalizeAction(value: unknown): CrabbySettingsToolAction {
  const action = normalizeString(value);
  switch (action) {
    case "inspect":
    case "set_runtime_value":
    case "save_profile":
    case "delete_profile":
    case "activate_profile":
    case "sync_profiles_from_backend":
    case "sync_backend_vault_path":
      return action;
    default:
      return "inspect";
  }
}

async function setRuntimeValue(
  plugin: CrabbyPlugin,
  input: CrabbySettingsToolInput,
): Promise<CrabbySettingsToolResult> {
  const key = normalizeString(input.key);
  if (!RUNTIME_KEYS.has(key)) {
    return {
      ok: false,
      message:
        "set_runtime_value only supports backendUrl, backendEnvPath, " +
        "backendMcpConfigPath, or runtimeManifestUrl.",
      settings: buildSettingsSnapshot(plugin),
    };
  }

  const value = normalizeRuntimeValue(key, input.value);
  (plugin.settings as unknown as Record<string, unknown>)[key] = value;
  await plugin.saveSettings();
  if (key === "backendUrl") {
    window.setTimeout(() => plugin.restartClientToolBridge(), 0);
  }

  return {
    ok: true,
    message: `Updated plugin setting ${key}.`,
    changed: [key],
    settings: buildSettingsSnapshot(plugin),
  };
}

async function saveProfile(
  plugin: CrabbyPlugin,
  input: CrabbySettingsToolInput,
): Promise<CrabbySettingsToolResult> {
  const profile = normalizeProfile(input.profile);
  if (!profile) {
    return {
      ok: false,
      message: "save_profile requires a complete profile payload.",
      settings: buildSettingsSnapshot(plugin),
    };
  }

  const client = new AgentClient(plugin.settings.backendUrl);
  const result = await saveLlmProfileToBackend(
    plugin.settings,
    profile,
    client,
    Boolean(input.activate),
  );
  if (!result.ok) {
    return {
      ok: false,
      message: result.message,
      settings: buildSettingsSnapshot(plugin),
    };
  }

  await plugin.saveSettings();
  return {
    ok: true,
    message: result.message,
    changed: input.activate ? ["llmProfiles", "activeProfileId"] : ["llmProfiles"],
    settings: buildSettingsSnapshot(plugin),
  };
}

async function deleteProfile(
  plugin: CrabbyPlugin,
  input: CrabbySettingsToolInput,
): Promise<CrabbySettingsToolResult> {
  const profileId = normalizeString(input.profile_id);
  if (!profileId) {
    return {
      ok: false,
      message: "delete_profile requires profile_id.",
      settings: buildSettingsSnapshot(plugin),
    };
  }

  const client = new AgentClient(plugin.settings.backendUrl);
  const result = await deleteLlmProfileFromBackend(
    plugin.settings,
    profileId,
    client,
  );
  if (!result.ok) {
    return {
      ok: false,
      message: result.message,
      settings: buildSettingsSnapshot(plugin),
    };
  }

  await plugin.saveSettings();
  return {
    ok: true,
    message: result.message,
    changed: ["llmProfiles", "activeProfileId"],
    settings: buildSettingsSnapshot(plugin),
  };
}

async function activateProfile(
  plugin: CrabbyPlugin,
  input: CrabbySettingsToolInput,
): Promise<CrabbySettingsToolResult> {
  const profileId = normalizeString(input.profile_id);
  if (!profileId) {
    return {
      ok: false,
      message: "activate_profile requires profile_id.",
      settings: buildSettingsSnapshot(plugin),
    };
  }

  const client = new AgentClient(plugin.settings.backendUrl);
  const result = await activateLlmProfileOnBackend(
    plugin.settings,
    profileId,
    client,
  );
  if (!result.ok) {
    return {
      ok: false,
      message: result.message,
      settings: buildSettingsSnapshot(plugin),
    };
  }

  await plugin.saveSettings();
  return {
    ok: true,
    message: result.message,
    changed: ["activeProfileId", "llmProfiles"],
    settings: buildSettingsSnapshot(plugin),
  };
}

async function syncProfilesFromBackend(
  plugin: CrabbyPlugin,
): Promise<CrabbySettingsToolResult> {
  const client = new AgentClient(plugin.settings.backendUrl);
  const result = await fetchLlmProfilesFromBackend(plugin.settings, client);
  if (!result.ok) {
    return {
      ok: false,
      message: result.message,
      settings: buildSettingsSnapshot(plugin),
    };
  }

  await plugin.saveSettings();
  return {
    ok: true,
    message: result.message,
    changed: ["llmProfiles", "activeProfileId"],
    settings: buildSettingsSnapshot(plugin),
  };
}

async function syncBackendVaultPath(
  plugin: CrabbyPlugin,
): Promise<CrabbySettingsToolResult> {
  const result = await plugin.ensureBackendVaultPathSynced();
  return {
    ok: result.ok,
    message: result.message,
    changed: result.changed ? ["backend_vault_path"] : [],
    settings: buildSettingsSnapshot(plugin),
  };
}

function buildSettingsSnapshot(plugin: CrabbyPlugin): Record<string, unknown> {
  let pluginDataPath = "";
  let runtimeStatus: unknown = null;
  try {
    const layout = resolvePluginRuntimeLayout(plugin.app);
    pluginDataPath = join(layout.pluginDir, "data.json");
  } catch {
    pluginDataPath = "";
  }

  try {
    runtimeStatus = plugin.runtimeManager?.getStatus() ?? null;
  } catch {
    runtimeStatus = null;
  }

  return {
    pluginDataPath,
    currentVaultPath: plugin.getCurrentVaultPath(),
    backendUrl: plugin.settings.backendUrl,
    backendEnvPath: plugin.settings.backendEnvPath,
    backendMcpConfigPath: plugin.settings.backendMcpConfigPath,
    runtimeManifestUrl: plugin.settings.runtimeManifestUrl,
    diary: plugin.settings.diary,
    diaryConfigPath: resolveDiaryConfigPath(plugin.getCurrentVaultPath()),
    activeProfileId: plugin.settings.activeProfileId,
    llmProfiles: plugin.settings.llmProfiles.map(sanitizeProfile),
    runtimeStatus,
    backendEnvPathExists: pathExists(plugin.settings.backendEnvPath),
    backendMcpConfigPathExists: pathExists(plugin.settings.backendMcpConfigPath),
    diaryConfigPathExists: pathExists(resolveDiaryConfigPath(plugin.getCurrentVaultPath())),
  };
}

function sanitizeProfile(profile: LlmProfile): Record<string, unknown> {
  return {
    id: profile.id,
    name: profile.name,
    provider: profile.provider,
    model: profile.model,
    baseUrl: profile.baseUrl,
    supportsVision: profile.supportsVision,
    thinkingMode: profile.thinkingMode,
    thinkingEffort: profile.thinkingEffort,
    thinkingBudgetTokens: profile.thinkingBudgetTokens,
    reasoningSplit: profile.reasoningSplit,
    isDraft: profile.isDraft === true,
    hasApiKey: profile.apiKey.trim().length > 0,
    apiKeyMasked: maskSecret(profile.apiKey),
  };
}

function normalizeProfile(profile: unknown): LlmProfile | null {
  if (!profile || typeof profile !== "object") {
    return null;
  }
  const record = profile as Record<string, unknown>;
  const id = normalizeString(record.id);
  const name = normalizeString(record.name);
  const model = normalizeString(record.model);
  if (!id || !name || !model) {
    return null;
  }

  return {
    id,
    name,
    provider: normalizeLlmProviderId(record.provider),
    model,
    baseUrl: normalizeString(record.baseUrl),
    apiKey: normalizeString(record.apiKey),
    supportsVision: normalizeBoolean(record.supportsVision),
    thinkingMode: normalizeString(record.thinkingMode),
    thinkingEffort: normalizeString(record.thinkingEffort),
    thinkingBudgetTokens: normalizeString(record.thinkingBudgetTokens, "1024"),
    reasoningSplit: normalizeBoolean(record.reasoningSplit),
    isDraft: normalizeBoolean(record.isDraft),
  };
}

function normalizeString(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value.trim() : fallback;
}

function normalizeRuntimeValue(key: string, value: unknown): string {
  const normalized = normalizeString(value);
  if (!normalized) {
    return "";
  }
  if (key === "backendEnvPath" || key === "backendMcpConfigPath") {
    return resolve(normalized);
  }
  return normalized;
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

function maskSecret(secret: string): string {
  const trimmed = secret.trim();
  if (!trimmed) {
    return "";
  }
  if (trimmed.length <= 6) {
    return "*".repeat(trimmed.length);
  }
  return `${trimmed.slice(0, 4)}...${trimmed.slice(-2)}`;
}

function pathExists(targetPath: string): boolean {
  if (!targetPath) {
    return false;
  }
  try {
    return existsSync(targetPath);
  } catch {
    return false;
  }
}
