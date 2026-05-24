import type { App } from "obsidian";
import { normalizePath } from "obsidian";

export interface WingRule {
  match: string;
  wing: string;
}

export interface WingConfig {
  rules: WingRule[];
  default_wing: string;
  exclude: string[];
}

const CONFIG_PATH = ".crabby/config/search-wings.json";

export const DEFAULT_WING_CONFIG: WingConfig = {
  rules: [],
  default_wing: "vault_default",
  exclude: [".crabby/**", ".obsidian/**", ".git/**"],
};

export async function loadWingConfig(app: App): Promise<WingConfig> {
  const adapter = app.vault.adapter;
  const p = normalizePath(CONFIG_PATH);
  if (!(await adapter.exists(p))) {
    return DEFAULT_WING_CONFIG;
  }
  try {
    const raw = JSON.parse(await adapter.read(p)) as Partial<WingConfig>;
    return {
      rules: Array.isArray(raw.rules) ? raw.rules : [],
      default_wing: raw.default_wing || DEFAULT_WING_CONFIG.default_wing,
      exclude: Array.isArray(raw.exclude)
        ? raw.exclude
        : DEFAULT_WING_CONFIG.exclude,
    };
  } catch (error) {
    console.warn("[Crabby] search-wings.json unreadable; using defaults", error);
    return DEFAULT_WING_CONFIG;
  }
}

interface CompiledRule {
  regex: RegExp;
  wingTemplate: string;
  excludesOnly: boolean;
}

function compileRule(pattern: string, wingTemplate: string, exclude: boolean): CompiledRule {
  // Glob → regex. Supports `*` (within segment), `**` (any depth),
  // `{n}` capture references via parens around `*`/`**` segments.
  let regex = "^";
  let i = 0;
  while (i < pattern.length) {
    const c = pattern[i];
    if (c === "*" && pattern[i + 1] === "*") {
      regex += "(.*)";
      i += 2;
      if (pattern[i] === "/") i += 1;
      continue;
    }
    if (c === "*") {
      regex += "([^/]*)";
      i += 1;
      continue;
    }
    if (/[.+^${}()|[\]\\]/.test(c)) {
      regex += "\\" + c;
    } else {
      regex += c;
    }
    i += 1;
  }
  regex += "$";
  return { regex: new RegExp(regex), wingTemplate, excludesOnly: exclude };
}

export interface WingMapper {
  pathToWing(vaultRelPath: string): string | null;
  topLevelWingFor(vaultRelPath: string): string;
}

export function buildWingMapper(config: WingConfig): WingMapper {
  const excludeRules = config.exclude.map((p) => compileRule(p, "", true));
  const rules = config.rules.map((r) => compileRule(r.match, r.wing, false));

  function applyTemplate(template: string, captures: string[]): string {
    return template.replace(/\{(\d+)\}/g, (_, idx) => {
      const i = Number(idx);
      return captures[i - 1] ?? "";
    });
  }

  function topLevel(vaultRelPath: string): string {
    const segments = vaultRelPath.split("/");
    if (segments.length <= 1) {
      return config.default_wing;
    }
    const top = segments[0];
    if (!top) return config.default_wing;
    return `vault:${top}`;
  }

  return {
    pathToWing(vaultRelPath) {
      for (const rule of excludeRules) {
        if (rule.regex.test(vaultRelPath)) {
          return null;
        }
      }
      for (const rule of rules) {
        const m = rule.regex.exec(vaultRelPath);
        if (m) {
          return applyTemplate(rule.wingTemplate, m.slice(1));
        }
      }
      return topLevel(vaultRelPath);
    },
    topLevelWingFor: topLevel,
  };
}
