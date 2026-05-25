import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";

import type {
  AgentClient,
  BackendLlmProfile,
  BackendLlmProfilesResponse,
  ReloadConfigResult,
} from "../api/client";
import type { CrabbySettings, LlmProfile } from "../settings";
import {
  getLlmProviderPreset,
  isLlmProviderId,
  type LlmProviderId,
} from "./llmProviders";

export const ADMIN_RELOAD_HEADER = "X-Crabby-Admin-Token";
const ADMIN_ENABLED_KEY = "CRABBY_ADMIN_ENABLED";
const ADMIN_TOKEN_KEY = "CRABBY_ADMIN_TOKEN";
const VAULT_PATH_KEY = "VAULT_PATH";
const ENV_ASSIGNMENT = /^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$/;
const PROVIDER_API_KEY_KEYS = [
  "ANTHROPIC_API_KEY",
  "OPENAI_API_KEY",
  "DEEPSEEK_API_KEY",
  "DASHSCOPE_API_KEY",
  "BAILIAN_CODING_PLAN_API_KEY",
  "MOONSHOT_API_KEY",
  "KIMI_API_KEY",
  "MINIMAX_API_KEY",
  "ZAI_API_KEY",
];
const PROVIDER_BASE_URL_KEYS = [
  "OPENAI_BASE_URL",
  "OLLAMA_BASE_URL",
  "KIMI_BASE_URL",
];
const PROFILE_ENV_KEY =
  /^PROFILE_([A-Za-z0-9_-]+)_(NAME|PROVIDER|MODEL|BASE_URL|API_KEY|SUPPORTS_VISION|THINKING_MODE|THINKING_EFFORT|THINKING_BUDGET_TOKENS|REASONING_SPLIT)$/;

export interface BackendEnvPathResolution {
  ok: boolean;
  envPath?: string;
  derivedFromLegacyPath: boolean;
  message: string;
}

export interface LocalConfigResult {
  ok: boolean;
  message: string;
  envPath?: string;
  needsMigration?: boolean;
  reloadStatus?: number | null;
  changed?: boolean;
}

export interface BackendProfileResult extends LocalConfigResult {
  profiles?: LlmProfile[];
  activeProfileId?: string;
}

export function resolveBackendEnvPath(
  settings: Pick<CrabbySettings, "backendEnvPath" | "backendPath">,
): BackendEnvPathResolution {
  const backendEnvPath = settings.backendEnvPath?.trim();
  if (backendEnvPath) {
    const envPath = resolve(backendEnvPath);
    if (!existsSync(envPath)) {
      return {
        ok: false,
        envPath,
        derivedFromLegacyPath: false,
        message: `后端 .env 配置文件 ${envPath} 不存在。`,
      };
    }
    return {
      ok: true,
      envPath,
      derivedFromLegacyPath: false,
      message: "",
    };
  }

  const legacyPath = settings.backendPath?.trim();
  if (legacyPath) {
    const envPath = resolve(legacyPath, ".env");
    if (!existsSync(envPath)) {
      return {
        ok: false,
        envPath,
        derivedFromLegacyPath: true,
        message: `遗留路径 ${envPath} 不存在，请重新配置后端 .env 路径。`,
      };
    }
    const token = readEnvValue(envPath, "CRABBY_ADMIN_TOKEN");
    if (!token?.trim()) {
      return {
        ok: false,
        envPath,
        derivedFromLegacyPath: true,
        message:
          "遗留配置文件不完整（缺少 CRABBY_ADMIN_TOKEN）。" +
          "请重新在「本地后端程序」区域安装并启动后端，或手动清空" +
          "后端 .env 路径设置后重新初始化。",
      };
    }
    return {
      ok: true,
      envPath,
      derivedFromLegacyPath: true,
      message: "",
    };
  }

  return {
    ok: false,
    derivedFromLegacyPath: false,
    message:
      "后端尚未初始化。请先在「本地后端程序」区域安装并启动后端，" +
      "完成后 .env 路径将自动配置完毕，无需手动填写。",
  };
}

export function readEnvValue(envPath: string, key: string): string | null {
  if (!existsSync(envPath)) {
    return null;
  }

  for (const [envKey, value] of readEnvAssignments(envPath)) {
    if (envKey === key) {
      return value;
    }
  }

  return null;
}

export function resolveBackendAdminToken(
  settings: Pick<CrabbySettings, "backendEnvPath" | "backendPath">,
): { ok: boolean; adminToken?: string; envPath?: string; message: string } {
  const resolution = resolveBackendEnvPath(settings);
  if (!resolution.ok || !resolution.envPath) {
    return {
      ok: false,
      message: resolution.message,
    };
  }

  const adminToken = readEnvValue(resolution.envPath, ADMIN_TOKEN_KEY)?.trim();
  if (!adminToken) {
    return {
      ok: false,
      envPath: resolution.envPath,
      message: `${resolution.envPath} 缺少 ${ADMIN_TOKEN_KEY}。`,
    };
  }

  return {
    ok: true,
    adminToken,
    envPath: resolution.envPath,
    message: "",
  };
}

function readEnvAssignments(envPath: string): Array<[string, string]> {
  if (!existsSync(envPath)) {
    return [];
  }

  const content = readFileSync(envPath, "utf8");
  const lines = content.split(/\r?\n/);
  const assignments: Array<[string, string]> = [];

  for (const line of lines) {
    const match = line.match(ENV_ASSIGNMENT);
    if (match) {
      assignments.push([match[1], stripWrappingQuotes(match[2])]);
    }
  }

  return assignments;
}

export function upsertEnvFile(
  envPath: string,
  envMap: Record<string, string | null>,
): void {
  const existing = existsSync(envPath) ? readFileSync(envPath, "utf8") : "";
  const newline = existing.includes("\r\n") ? "\r\n" : "\n";
  const lines = existing === "" ? [] : existing.split(/\r?\n/);
  const pending = new Map(Object.entries(envMap));
  const nextLines: string[] = [];

  for (const line of lines) {
    const match = line.match(ENV_ASSIGNMENT);
    if (!match) {
      nextLines.push(line);
      continue;
    }

    const key = match[1];
    if (!pending.has(key)) {
      nextLines.push(line);
      continue;
    }

    const value = pending.get(key) ?? null;
    pending.delete(key);
    if (value !== null) {
      nextLines.push(`${key}=${serializeEnvValue(value)}`);
    }
  }

  for (const [key, value] of pending.entries()) {
    if (value !== null) {
      nextLines.push(`${key}=${serializeEnvValue(value)}`);
    }
  }

  const nextContent = nextLines.join(newline);
  writeFileSync(envPath, nextContent === "" ? "" : `${nextContent}${newline}`, "utf8");
}

export type RuntimeEnvReloadMode = "settings" | "full";

export interface RuntimeIntegerInputResult {
  ok: boolean;
  value: number | null;
  envValue: string | null;
  message: string;
}

export function parseRuntimeEnvBoolean(
  value: string | null | undefined,
  fallback: boolean,
): boolean {
  if (value === null || value === undefined) {
    return fallback;
  }

  const normalized = value.trim().toLowerCase();
  if (!normalized) {
    return fallback;
  }
  if (["1", "true", "yes", "on"].includes(normalized)) {
    return true;
  }
  if (["0", "false", "no", "off"].includes(normalized)) {
    return false;
  }
  return fallback;
}

export function parseRuntimeEnvInteger(
  value: string | null | undefined,
  fallback: number,
): number {
  if (value === null || value === undefined) {
    return fallback;
  }

  const normalized = value.trim();
  if (!/^\d+$/.test(normalized)) {
    return fallback;
  }

  const parsed = Number(normalized);
  return Number.isSafeInteger(parsed) ? parsed : fallback;
}

export function normalizeRuntimeIntegerInput(
  value: string,
): RuntimeIntegerInputResult {
  const normalized = value.trim();
  if (!normalized) {
    return {
      ok: true,
      value: null,
      envValue: null,
      message: "",
    };
  }

  if (!/^\d+$/.test(normalized)) {
    return {
      ok: false,
      value: null,
      envValue: null,
      message: "请输入非负整数，或留空恢复默认值。",
    };
  }

  const parsed = Number(normalized);
  if (!Number.isSafeInteger(parsed)) {
    return {
      ok: false,
      value: null,
      envValue: null,
      message: "数值过大，请输入一个安全的非负整数。",
    };
  }

  return {
    ok: true,
    value: parsed,
    envValue: String(parsed),
    message: "",
  };
}

export function readRuntimeEnvBoolean(
  settings: Pick<CrabbySettings, "backendEnvPath" | "backendPath">,
  key: string,
  fallback: boolean,
): boolean {
  const resolution = resolveBackendEnvPath(settings);
  if (!resolution.ok || !resolution.envPath) {
    return fallback;
  }
  return parseRuntimeEnvBoolean(readEnvValue(resolution.envPath, key), fallback);
}

export function readRuntimeEnvInteger(
  settings: Pick<CrabbySettings, "backendEnvPath" | "backendPath">,
  key: string,
  fallback: number,
): number {
  const resolution = resolveBackendEnvPath(settings);
  if (!resolution.ok || !resolution.envPath) {
    return fallback;
  }
  return parseRuntimeEnvInteger(readEnvValue(resolution.envPath, key), fallback);
}

export async function saveRuntimeEnvSetting(
  settings: Pick<CrabbySettings, "backendEnvPath" | "backendPath">,
  key: string,
  value: string | null,
  client: Pick<AgentClient, "reloadSettings" | "reloadConfig">,
  reloadMode: RuntimeEnvReloadMode = "settings",
): Promise<LocalConfigResult> {
  const resolution = resolveBackendEnvPath(settings);
  if (!resolution.ok || !resolution.envPath) {
    return {
      ok: false,
      message: resolution.message,
      changed: false,
    };
  }

  upsertEnvFile(resolution.envPath, { [key]: value });

  const savedLabel = value === null ? `${key}=<default>` : `${key}=${value}`;
  const adminEnabled = readEnvValue(resolution.envPath, ADMIN_ENABLED_KEY);
  if (!isTruthyEnvValue(adminEnabled)) {
    return {
      ok: false,
      envPath: resolution.envPath,
      needsMigration: resolution.derivedFromLegacyPath,
      changed: true,
      message:
        `已将 ${savedLabel} 保存到 ${resolution.envPath}，但后端热重载未开启。` +
        `请设置 ${ADMIN_ENABLED_KEY}=true 后再试，或重启后端。`,
    };
  }

  const adminToken = readEnvValue(resolution.envPath, ADMIN_TOKEN_KEY)?.trim();
  if (!adminToken) {
    return {
      ok: false,
      envPath: resolution.envPath,
      needsMigration: resolution.derivedFromLegacyPath,
      changed: true,
      message:
        `已将 ${savedLabel} 保存到 ${resolution.envPath}，但缺少 ${ADMIN_TOKEN_KEY}。` +
        "请稍后重载或重启后端使其生效。",
    };
  }

  const reloadResult =
    reloadMode === "full"
      ? await client.reloadConfig(adminToken)
      : await client.reloadSettings(adminToken);
  if (reloadResult.ok) {
    return {
      ok: true,
      envPath: resolution.envPath,
      needsMigration: resolution.derivedFromLegacyPath,
      reloadStatus: reloadResult.status,
      changed: true,
      message:
        reloadMode === "full"
          ? `已保存 ${savedLabel}，并完成后端配置重载。`
          : `已保存 ${savedLabel}，并完成后端设置热重载。`,
    };
  }

  return {
    ok: false,
    envPath: resolution.envPath,
    needsMigration: resolution.derivedFromLegacyPath,
    reloadStatus: reloadResult.status,
    changed: true,
    message:
      `已将 ${savedLabel} 保存到 ${resolution.envPath}，但后端重载失败` +
      formatReloadSuffix(reloadResult) +
      "。请稍后重载或重启后端使其生效。",
  };
}

export function buildActiveProfileEnvMap(
  profile: Pick<
    LlmProfile,
    | "id"
    | "provider"
    | "model"
    | "baseUrl"
    | "apiKey"
    | "supportsVision"
    | "thinkingMode"
    | "thinkingEffort"
    | "thinkingBudgetTokens"
    | "reasoningSplit"
  >,
): Record<string, string | null> {
  const preset = getLlmProviderPreset(profile.provider);
  const thinkingMode = profile.thinkingMode?.trim() ?? "";
  const thinkingEffort = profile.thinkingEffort?.trim() ?? "";
  const thinkingBudgetTokens = profile.thinkingBudgetTokens?.trim() ?? "";
  const envMap: Record<string, string | null> = {
    LLM_PROVIDER: profile.provider,
    LLM_MODEL: profile.model,
    LLM_API_KEY: null,
    LLM_BASE_URL: profile.baseUrl.trim() || null,
    LLM_SUPPORTS_VISION: profile.supportsVision ? "true" : "false",
    LLM_THINKING_MODE: thinkingMode || null,
    LLM_THINKING_BUDGET_TOKENS: thinkingBudgetTokens || null,
    LLM_REASONING_EFFORT: thinkingEffort || null,
    LLM_REASONING_SPLIT: profile.reasoningSplit ? "true" : null,
    ACTIVE_PROFILE_ID: profile.id,
  };

  for (const key of PROVIDER_API_KEY_KEYS) {
    envMap[key] = null;
  }
  for (const key of PROVIDER_BASE_URL_KEYS) {
    envMap[key] = null;
  }

  const apiKey = profile.apiKey.trim();
  if (apiKey) {
    envMap.LLM_API_KEY = apiKey;
    if (preset.apiKeyEnv && preset.apiKeyEnv !== "LLM_API_KEY") {
      envMap[preset.apiKeyEnv] = apiKey;
    }
  }

  const baseUrl = profile.baseUrl.trim();
  if (baseUrl) {
    envMap.LLM_BASE_URL = baseUrl;
    if (profile.provider === "openai") {
      envMap.OPENAI_BASE_URL = baseUrl;
    } else if (profile.provider === "kimi") {
      envMap.KIMI_BASE_URL = baseUrl;
    }
  }

  if (profile.provider === "anthropic") {
    envMap.LLM_BASE_URL = null;
  }

  return envMap;
}

export function buildSavedProfileEnvMap(
  profile: Pick<
    LlmProfile,
    | "id"
    | "name"
    | "provider"
    | "model"
    | "baseUrl"
    | "apiKey"
    | "supportsVision"
    | "thinkingMode"
    | "thinkingEffort"
    | "thinkingBudgetTokens"
    | "reasoningSplit"
  >,
): Record<string, string> {
  const prefix = `PROFILE_${profile.id}`;
  const thinkingMode = profile.thinkingMode ?? "";
  const thinkingEffort = profile.thinkingEffort ?? "";
  const thinkingBudgetTokens = profile.thinkingBudgetTokens ?? "";
  return {
    [`${prefix}_NAME`]: profile.name,
    [`${prefix}_PROVIDER`]: profile.provider,
    [`${prefix}_MODEL`]: profile.model,
    [`${prefix}_BASE_URL`]: profile.baseUrl,
    [`${prefix}_API_KEY`]: profile.apiKey,
    [`${prefix}_SUPPORTS_VISION`]: profile.supportsVision ? "true" : "false",
    [`${prefix}_THINKING_MODE`]: thinkingMode,
    [`${prefix}_THINKING_EFFORT`]: thinkingEffort,
    [`${prefix}_THINKING_BUDGET_TOKENS`]: thinkingBudgetTokens,
    [`${prefix}_REASONING_SPLIT`]: profile.reasoningSplit ? "true" : "false",
  };
}

export function readSavedProfilesFromEnv(envPath: string): LlmProfile[] {
  const snapshots = new Map<string, Record<string, string>>();

  for (const [key, value] of readEnvAssignments(envPath)) {
    const match = key.match(PROFILE_ENV_KEY);
    if (!match) {
      continue;
    }

    const [, id, field] = match;
    const snapshot = snapshots.get(id) ?? {};
    snapshot[field] = value;
    snapshots.set(id, snapshot);
  }

  return Array.from(snapshots.entries())
    .map(([id, snapshot]) => {
      const model = snapshot.MODEL?.trim() ?? "";
      if (!model) {
        return null;
      }

      const name = snapshot.NAME?.trim() || model || id;
      const baseUrl = snapshot.BASE_URL?.trim() ?? "";
      const provider = normalizeSavedProfileProvider(
        snapshot.PROVIDER,
        model,
        baseUrl,
        name,
      );

      return {
        id,
        name,
        provider,
        model,
        baseUrl,
        apiKey: snapshot.API_KEY?.trim() ?? "",
        supportsVision: isTruthyEnvValue(snapshot.SUPPORTS_VISION),
        thinkingMode: snapshot.THINKING_MODE?.trim() ?? "",
        thinkingEffort: snapshot.THINKING_EFFORT?.trim() ?? "",
        thinkingBudgetTokens:
          snapshot.THINKING_BUDGET_TOKENS?.trim() || "1024",
        reasoningSplit: isTruthyEnvValue(snapshot.REASONING_SPLIT),
      } satisfies LlmProfile;
    })
    .filter((profile): profile is LlmProfile => profile !== null);
}

export function mergeSavedProfilesFromEnv(
  settings: Pick<
    CrabbySettings,
    | "backendEnvPath"
    | "backendPath"
    | "llmProfiles"
    | "activeProfileId"
  >,
): boolean {
  const resolution = resolveBackendEnvPath(settings);
  if (!resolution.ok || !resolution.envPath) {
    return false;
  }

  const envProfiles = readSavedProfilesFromEnv(resolution.envPath);
  if (envProfiles.length === 0) {
    return false;
  }

  const before = JSON.stringify({
    llmProfiles: settings.llmProfiles,
    activeProfileId: settings.activeProfileId,
  });
  const existingById = new Map(
    settings.llmProfiles.map((profile) => [profile.id, profile]),
  );
  const envIds = new Set(envProfiles.map((profile) => profile.id));
  const mergedProfiles = envProfiles.map((profile) => {
    const existing = existingById.get(profile.id);
    return {
      ...profile,
      apiKey: profile.apiKey || existing?.apiKey || "",
    };
  });

  for (const profile of settings.llmProfiles) {
    if (!envIds.has(profile.id)) {
      mergedProfiles.push(profile);
    }
  }

  settings.llmProfiles = mergedProfiles;

  const activeProfileId = readEnvValue(resolution.envPath, "ACTIVE_PROFILE_ID");
  if (
    activeProfileId &&
    mergedProfiles.some((profile) => profile.id === activeProfileId)
  ) {
    settings.activeProfileId = activeProfileId;
  } else if (
    !settings.activeProfileId ||
    !mergedProfiles.some((profile) => profile.id === settings.activeProfileId)
  ) {
    settings.activeProfileId = mergedProfiles[0]?.id ?? "";
  }

  const after = JSON.stringify({
    llmProfiles: settings.llmProfiles,
    activeProfileId: settings.activeProfileId,
  });
  return before !== after;
}

export async function fetchLlmProfilesFromBackend(
  settings: Pick<
    CrabbySettings,
    "backendEnvPath" | "backendPath" | "llmProfiles" | "activeProfileId"
  >,
  client: Pick<AgentClient, "listLlmProfiles">,
): Promise<BackendProfileResult> {
  const token = resolveBackendAdminToken(settings);
  if (!token.ok || !token.adminToken) {
    return { ok: false, message: token.message, envPath: token.envPath };
  }

  const result = await client.listLlmProfiles(token.adminToken);
  return applyBackendProfileResult(settings, result, "已从后端读取 LLM 配置。");
}

export async function saveLlmProfileToBackend(
  settings: Pick<
    CrabbySettings,
    "backendEnvPath" | "backendPath" | "llmProfiles" | "activeProfileId"
  >,
  profile: LlmProfile,
  client: Pick<AgentClient, "saveLlmProfile">,
  activate = false,
): Promise<BackendProfileResult> {
  const token = resolveBackendAdminToken(settings);
  if (!token.ok || !token.adminToken) {
    return { ok: false, message: token.message, envPath: token.envPath };
  }

  const result = await client.saveLlmProfile(
    token.adminToken,
    toBackendLlmProfile(profile),
    activate,
  );
  return applyBackendProfileResult(
    settings,
    result,
    activate
      ? `已保存并启用 ${profile.name}。`
      : `已保存 ${profile.name} 到后端。`,
  );
}

export async function activateLlmProfileOnBackend(
  settings: Pick<
    CrabbySettings,
    "backendEnvPath" | "backendPath" | "llmProfiles" | "activeProfileId"
  >,
  profileId: string,
  client: Pick<AgentClient, "activateLlmProfile">,
): Promise<BackendProfileResult> {
  const token = resolveBackendAdminToken(settings);
  if (!token.ok || !token.adminToken) {
    return { ok: false, message: token.message, envPath: token.envPath };
  }

  const result = await client.activateLlmProfile(token.adminToken, profileId);
  return applyBackendProfileResult(settings, result, "已切换后端 LLM 配置。");
}

export async function deleteLlmProfileFromBackend(
  settings: Pick<
    CrabbySettings,
    "backendEnvPath" | "backendPath" | "llmProfiles" | "activeProfileId"
  >,
  profileId: string,
  client: Pick<AgentClient, "deleteLlmProfile">,
): Promise<BackendProfileResult> {
  const token = resolveBackendAdminToken(settings);
  if (!token.ok || !token.adminToken) {
    return { ok: false, message: token.message, envPath: token.envPath };
  }

  const result = await client.deleteLlmProfile(token.adminToken, profileId);
  return applyBackendProfileResult(settings, result, "已从后端删除 LLM 配置。");
}

function applyBackendProfileResult(
  settings: Pick<CrabbySettings, "llmProfiles" | "activeProfileId">,
  result: {
    ok: boolean;
    status: number | null;
    detail?: string | null;
    data?: BackendLlmProfilesResponse;
  },
  successMessage: string,
): BackendProfileResult {
  if (!result.ok || !result.data) {
    return {
      ok: false,
      reloadStatus: result.status,
      message: formatBackendProfileFailure(result),
    };
  }

  applyBackendProfileState(settings, result.data);
  return {
    ok: true,
    envPath: result.data.envPath,
    reloadStatus: result.status,
    profiles: settings.llmProfiles,
    activeProfileId: settings.activeProfileId,
    message: successMessage,
  };
}

function applyBackendProfileState(
  settings: Pick<CrabbySettings, "llmProfiles" | "activeProfileId">,
  data: BackendLlmProfilesResponse,
): void {
  const backendProfiles = data.profiles.map(fromBackendLlmProfile);
  const backendProfileIds = new Set(backendProfiles.map((profile) => profile.id));
  const draftProfiles = settings.llmProfiles.filter(
    (profile) => profile.isDraft === true && !backendProfileIds.has(profile.id),
  );
  const previousActiveProfileId = settings.activeProfileId;

  settings.llmProfiles = [...backendProfiles, ...draftProfiles];
  settings.activeProfileId =
    data.activeProfileId ||
    (draftProfiles.some((profile) => profile.id === previousActiveProfileId)
      ? previousActiveProfileId
      : "");
}

function toBackendLlmProfile(profile: LlmProfile): BackendLlmProfile {
  return {
    id: profile.id,
    name: profile.name,
    provider: profile.provider,
    model: profile.model,
    baseUrl: profile.baseUrl,
    apiKey: profile.apiKey,
    supportsVision: profile.supportsVision,
    thinkingMode: profile.thinkingMode,
    thinkingEffort: profile.thinkingEffort,
    thinkingBudgetTokens: profile.thinkingBudgetTokens,
    reasoningSplit: profile.reasoningSplit,
  };
}

function fromBackendLlmProfile(profile: BackendLlmProfile): LlmProfile {
  return {
    id: profile.id,
    name: profile.name,
    provider: isLlmProviderId(profile.provider)
      ? profile.provider
      : "custom_openai",
    model: profile.model,
    baseUrl: profile.baseUrl,
    apiKey: profile.apiKey,
    supportsVision: Boolean(profile.supportsVision),
    thinkingMode: profile.thinkingMode,
    thinkingEffort: profile.thinkingEffort,
    thinkingBudgetTokens: profile.thinkingBudgetTokens || "1024",
    reasoningSplit: Boolean(profile.reasoningSplit),
  };
}

function formatBackendProfileFailure(result: {
  status: number | null;
  detail?: string | null;
}): string {
  if (result.status === null) {
    return "后端当前不可访问。";
  }
  return result.detail || `HTTP ${result.status}`;
}

function normalizeSavedProfileProvider(
  value: string | undefined,
  model: string,
  baseUrl: string,
  name: string,
): LlmProviderId {
  const provider = value?.trim();
  const inferred = inferProviderFromProfile(model, baseUrl, name);

  if (!provider) {
    return inferred ?? "custom_openai";
  }

  if ((provider === "openai" || provider === "custom_openai") && inferred) {
    return inferred;
  }

  return isLlmProviderId(provider) ? provider : inferred ?? "custom_openai";
}

function inferProviderFromProfile(
  model: string,
  baseUrl: string,
  name: string,
): LlmProviderId | null {
  const text = `${model} ${baseUrl} ${name}`.toLowerCase();

  if (
    text.includes("coding.dashscope") ||
    text.includes("coding-intl.dashscope") ||
    text.includes("coding plan")
  ) {
    return "qwen";
  }
  if (text.includes("deepseek")) {
    return "deepseek";
  }
  if (text.includes("minimax") || text.includes("minimaxi")) {
    return "minimax";
  }
  if (/\bqwen3[.-]/.test(text)) {
    return "qwen";
  }
  if (text.includes("moonshot") || /\bkimi/.test(text)) {
    return "kimi";
  }
  if (text.includes("bigmodel") || /\bglm-/.test(text)) {
    return "zhipu";
  }
  if (text.includes("anthropic") || text.includes("claude")) {
    return "anthropic";
  }
  if (text.includes("ollama") || text.includes("localhost:11434")) {
    return "custom_openai";
  }

  return null;
}

export function getBackendEnvPathInputValue(
  settings: Pick<CrabbySettings, "backendEnvPath" | "backendPath">,
): string {
  const backendEnvPath = settings.backendEnvPath?.trim();
  if (backendEnvPath) {
    return resolve(backendEnvPath);
  }
  const legacyPath = settings.backendPath?.trim();
  if (legacyPath) {
    return resolve(legacyPath, ".env");
  }
  return "";
}

export async function saveProfileSnapshotLocally(
  settings: Pick<CrabbySettings, "backendEnvPath" | "backendPath">,
  profile: Pick<
    LlmProfile,
    | "id"
    | "name"
    | "provider"
    | "model"
    | "baseUrl"
    | "apiKey"
    | "supportsVision"
    | "thinkingMode"
    | "thinkingEffort"
    | "thinkingBudgetTokens"
    | "reasoningSplit"
  >,
): Promise<LocalConfigResult> {
  const resolution = resolveBackendEnvPath(settings);
  if (!resolution.ok || !resolution.envPath) {
    return {
      ok: false,
      message: resolution.message,
    };
  }

  upsertEnvFile(resolution.envPath, buildSavedProfileEnvMap(profile));
  return {
    ok: true,
    envPath: resolution.envPath,
    needsMigration: resolution.derivedFromLegacyPath,
    message: resolution.derivedFromLegacyPath
      ? `已将配置快照保存到 ${resolution.envPath}。${resolution.message}`
      : `已将配置快照保存到 ${resolution.envPath}。`,
  };
}

export async function applyActiveProfileLocally(
  settings: Pick<CrabbySettings, "backendEnvPath" | "backendPath">,
  profile: Pick<
    LlmProfile,
    | "id"
    | "name"
    | "provider"
    | "model"
    | "baseUrl"
    | "apiKey"
    | "supportsVision"
    | "thinkingMode"
    | "thinkingEffort"
    | "thinkingBudgetTokens"
    | "reasoningSplit"
  >,
  client: Pick<AgentClient, "reloadSettings">,
): Promise<LocalConfigResult> {
  const resolution = resolveBackendEnvPath(settings);
  if (!resolution.ok || !resolution.envPath) {
    return {
      ok: false,
      message: resolution.message,
    };
  }

  upsertEnvFile(resolution.envPath, buildActiveProfileEnvMap(profile));

  const adminEnabled = readEnvValue(resolution.envPath, ADMIN_ENABLED_KEY);
  if (!isTruthyEnvValue(adminEnabled)) {
    return {
      ok: false,
      envPath: resolution.envPath,
      needsMigration: resolution.derivedFromLegacyPath,
      message:
        `已将 ${profile.name} 写入 ${resolution.envPath}，但后端热重载未开启。` +
        `请设置 ${ADMIN_ENABLED_KEY}=true 后再试。`,
    };
  }

  const adminToken = readEnvValue(resolution.envPath, ADMIN_TOKEN_KEY)?.trim();
  if (!adminToken) {
    return {
      ok: false,
      envPath: resolution.envPath,
      needsMigration: resolution.derivedFromLegacyPath,
      message:
        `已将 ${profile.name} 写入 ${resolution.envPath}，但缺少 ${ADMIN_TOKEN_KEY}。`,
    };
  }

  const reloadResult = await client.reloadSettings(adminToken);
  if (reloadResult.ok) {
    return {
      ok: true,
      envPath: resolution.envPath,
      needsMigration: resolution.derivedFromLegacyPath,
      reloadStatus: reloadResult.status,
      message: resolution.derivedFromLegacyPath
        ? `已切换到 ${profile.name}，并完成后端热重载。${resolution.message}`
        : `已切换到 ${profile.name}，并完成后端热重载。`,
    };
  }

  return {
    ok: false,
    envPath: resolution.envPath,
    needsMigration: resolution.derivedFromLegacyPath,
    reloadStatus: reloadResult.status,
    message:
      `已将 ${profile.name} 写入 ${resolution.envPath}，但后端热重载失败` +
      formatReloadSuffix(reloadResult) +
      "。",
  };
}

export async function switchActiveProfileLocally(
  settings: Pick<
    CrabbySettings,
    "backendEnvPath" | "backendPath" | "activeProfileId"
  >,
  profile: Pick<
    LlmProfile,
    | "id"
    | "name"
    | "provider"
    | "model"
    | "baseUrl"
    | "apiKey"
    | "supportsVision"
    | "thinkingMode"
    | "thinkingEffort"
    | "thinkingBudgetTokens"
    | "reasoningSplit"
  >,
  client: Pick<AgentClient, "reloadSettings">,
): Promise<LocalConfigResult> {
  const result = await applyActiveProfileLocally(settings, profile, client);
  if (result.ok) {
    settings.activeProfileId = profile.id;
  }
  return result;
}

export async function syncVaultPathLocally(
  settings: Pick<CrabbySettings, "backendEnvPath" | "backendPath">,
  vaultPath: string,
  client: Pick<AgentClient, "reloadSettings">,
): Promise<LocalConfigResult> {
  const resolution = resolveBackendEnvPath(settings);
  if (!resolution.ok || !resolution.envPath) {
    return {
      ok: false,
      message: resolution.message,
      changed: false,
    };
  }

  const nextVaultPath = vaultPath.trim();
  if (!nextVaultPath) {
    return {
      ok: false,
      envPath: resolution.envPath,
      needsMigration: resolution.derivedFromLegacyPath,
      changed: false,
      message: "无法检测当前 Obsidian vault 路径。",
    };
  }

  const resolvedVaultPath = resolve(nextVaultPath);
  const currentVaultPath = readEnvValue(resolution.envPath, VAULT_PATH_KEY);
  if (currentVaultPath && isSameFilesystemPath(currentVaultPath, resolvedVaultPath)) {
    return {
      ok: true,
      envPath: resolution.envPath,
      needsMigration: resolution.derivedFromLegacyPath,
      changed: false,
      message: `当前 vault 路径已经同步：${resolvedVaultPath}`,
    };
  }

  upsertEnvFile(resolution.envPath, {
    [VAULT_PATH_KEY]: resolvedVaultPath,
  });

  const adminEnabled = readEnvValue(resolution.envPath, ADMIN_ENABLED_KEY);
  if (!isTruthyEnvValue(adminEnabled)) {
    return {
      ok: false,
      envPath: resolution.envPath,
      needsMigration: resolution.derivedFromLegacyPath,
      changed: true,
      message:
        `已将 ${VAULT_PATH_KEY}=${resolvedVaultPath} 保存到 ${resolution.envPath}，但后端热重载未开启。` +
        `请设置 ${ADMIN_ENABLED_KEY}=true 后再试。`,
    };
  }

  const adminToken = readEnvValue(resolution.envPath, ADMIN_TOKEN_KEY)?.trim();
  if (!adminToken) {
    return {
      ok: false,
      envPath: resolution.envPath,
      needsMigration: resolution.derivedFromLegacyPath,
      changed: true,
      message:
        `已将 ${VAULT_PATH_KEY}=${resolvedVaultPath} 保存到 ${resolution.envPath}，但缺少 ${ADMIN_TOKEN_KEY}。`,
    };
  }

  const reloadResult = await client.reloadSettings(adminToken);
  if (reloadResult.ok) {
    return {
      ok: true,
      envPath: resolution.envPath,
      needsMigration: resolution.derivedFromLegacyPath,
      reloadStatus: reloadResult.status,
      changed: true,
      message: resolution.derivedFromLegacyPath
        ? `已同步 vault 路径到 ${resolvedVaultPath}，并完成后端热重载。${resolution.message}`
        : `已同步 vault 路径到 ${resolvedVaultPath}，并完成后端热重载。`,
    };
  }

  return {
    ok: false,
    envPath: resolution.envPath,
    needsMigration: resolution.derivedFromLegacyPath,
    reloadStatus: reloadResult.status,
    changed: true,
    message:
      `已将 ${VAULT_PATH_KEY}=${resolvedVaultPath} 保存到 ${resolution.envPath}，但后端重载失败` +
      formatReloadSuffix(reloadResult) +
      "。",
  };
}

export function isTruthyEnvValue(value: string | null | undefined): boolean {
  if (!value) {
    return false;
  }

  return ["1", "true", "yes", "on"].includes(value.trim().toLowerCase());
}

function formatReloadSuffix(reloadResult: ReloadConfigResult): string {
  if (reloadResult.status === null) {
    return "：后端当前不可访问";
  }

  if (reloadResult.detail) {
    return `（HTTP ${reloadResult.status}）：${reloadResult.detail}`;
  }

  return `（HTTP ${reloadResult.status}）`;
}

function isSameFilesystemPath(left: string, right: string): boolean {
  return normalizeFilesystemPath(left) === normalizeFilesystemPath(right);
}

function normalizeFilesystemPath(value: string): string {
  const normalized = resolve(value);
  return process.platform === "win32" ? normalized.toLowerCase() : normalized;
}

function stripWrappingQuotes(value: string): string {
  if (value.startsWith('"') && value.endsWith('"')) {
    try {
      return JSON.parse(value) as string;
    } catch {
      return value.slice(1, -1);
    }
  }

  if (value.startsWith("'") && value.endsWith("'")) {
    return value.slice(1, -1);
  }

  return value;
}

function serializeEnvValue(value: string): string {
  if (value === "") {
    return '""';
  }

  if (/[#\s"'\\]/.test(value)) {
    return JSON.stringify(value);
  }

  return value;
}
