import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";

export const DIARY_PERIODS = [
  "daily",
  "weekly",
  "monthly",
  "quarterly",
  "yearly",
] as const;

export type DiaryPeriod = (typeof DIARY_PERIODS)[number];

export interface DiarySettings {
  rootPath: string;
  templatePaths: Record<DiaryPeriod, string>;
}

export const DEFAULT_DIARY_SETTINGS: DiarySettings = {
  rootPath: "Journal",
  templatePaths: {
    daily: ".crabby/templates/diary/daily.md",
    weekly: ".crabby/templates/diary/weekly.md",
    monthly: ".crabby/templates/diary/monthly.md",
    quarterly: ".crabby/templates/diary/quarterly.md",
    yearly: ".crabby/templates/diary/yearly.md",
  },
};

export function normalizeDiarySettings(source: unknown): DiarySettings {
  const record = isRecord(source) ? source : {};
  const rootPath = normalizeVaultRelativePath(
    record.rootPath,
    DEFAULT_DIARY_SETTINGS.rootPath,
    "rootPath",
  );
  const rawTemplatePaths = isRecord(record.templatePaths)
    ? record.templatePaths
    : {};

  return {
    rootPath,
    templatePaths: {
      daily: normalizeVaultRelativePath(
        rawTemplatePaths.daily,
        DEFAULT_DIARY_SETTINGS.templatePaths.daily,
        "templatePaths.daily",
      ),
      weekly: normalizeVaultRelativePath(
        rawTemplatePaths.weekly,
        DEFAULT_DIARY_SETTINGS.templatePaths.weekly,
        "templatePaths.weekly",
      ),
      monthly: normalizeVaultRelativePath(
        rawTemplatePaths.monthly,
        DEFAULT_DIARY_SETTINGS.templatePaths.monthly,
        "templatePaths.monthly",
      ),
      quarterly: normalizeVaultRelativePath(
        rawTemplatePaths.quarterly,
        DEFAULT_DIARY_SETTINGS.templatePaths.quarterly,
        "templatePaths.quarterly",
      ),
      yearly: normalizeVaultRelativePath(
        rawTemplatePaths.yearly,
        DEFAULT_DIARY_SETTINGS.templatePaths.yearly,
        "templatePaths.yearly",
      ),
    },
  };
}

export function serializeDiarySettings(settings: DiarySettings): Record<string, unknown> {
  return {
    rootPath: settings.rootPath,
    templatePaths: { ...settings.templatePaths },
  };
}

export function readDiarySettingsFile(filePath: string): DiarySettings | null {
  if (!existsSync(filePath)) {
    return null;
  }
  try {
    const raw = JSON.parse(readFileSync(filePath, "utf8")) as unknown;
    return normalizeDiarySettings(raw);
  } catch {
    return null;
  }
}

export function writeDiarySettingsFile(filePath: string, settings: DiarySettings): void {
  mkdirSync(dirname(filePath), { recursive: true });
  writeFileSync(
    filePath,
    `${JSON.stringify(serializeDiarySettings(settings), null, 2)}\n`,
    "utf8",
  );
}

export function normalizeVaultRelativePath(
  value: unknown,
  fallback: string,
  fieldName: string,
): string {
  const raw = typeof value === "string" ? value.trim() : "";
  const source = raw || fallback;
  const normalized = source.replace(/\\/g, "/").trim();

  if (
    normalized.startsWith("/") ||
    normalized.startsWith("~") ||
    /^[A-Za-z]:/.test(normalized)
  ) {
    throw new Error(`${fieldName} 必须是 Vault-relative 路径。`);
  }

  const segments = normalized
    .split("/")
    .filter((segment) => segment && segment !== ".");
  if (segments.some((segment) => segment === "..")) {
    throw new Error(`${fieldName} 不能包含 ".."。`);
  }

  return segments.join("/") || fallback;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

export function resolveDiaryConfigPath(vaultRoot: string): string {
  return resolve(vaultRoot, ".crabby", "config", "diary.json");
}
