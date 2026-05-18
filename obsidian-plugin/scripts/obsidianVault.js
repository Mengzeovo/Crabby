const fs = require("fs");
const path = require("path");

function getObsidianConfigCandidates() {
  if (process.platform === "win32") {
    const appData = process.env.APPDATA;
    if (!appData) {
      return [];
    }
    return [
      path.join(appData, "obsidian", "obsidian.json"),
      path.join(appData, "Obsidian", "obsidian.json"),
    ];
  }

  if (process.platform === "darwin") {
    const home = process.env.HOME;
    if (!home) {
      return [];
    }
    return [
      path.join(home, "Library", "Application Support", "obsidian", "obsidian.json"),
    ];
  }

  // Linux / other Unix
  const xdgConfig = process.env.XDG_CONFIG_HOME
    || path.join(process.env.HOME || "", ".config");
  return [path.join(xdgConfig, "obsidian", "obsidian.json")];
}

const DEFAULT_VAULT = path.join(
  process.env.HOME || process.cwd(),
  process.platform === "darwin" ? "Documents" : "ObsidianVault",
);

function findObsidianConfigPath() {
  for (const candidate of getObsidianConfigCandidates()) {
    if (fs.existsSync(candidate)) {
      return candidate;
    }
  }
  return null;
}

function loadVaultEntries(configPath) {
  if (!configPath || !fs.existsSync(configPath)) {
    return [];
  }

  let parsed;
  try {
    const raw = fs.readFileSync(configPath, "utf8");
    parsed = JSON.parse(raw);
  } catch {
    return [];
  }

  const vaults = parsed && typeof parsed === "object" ? parsed.vaults : null;
  if (!vaults || typeof vaults !== "object") {
    return [];
  }

  return Object.values(vaults)
    .filter((entry) => entry && typeof entry.path === "string" && entry.path.trim())
    .map((entry) => ({
      path: path.resolve(entry.path.trim()),
      ts: Number(entry.ts) || 0,
      open: Boolean(entry.open),
    }));
}

function pickPreferredVault(entries) {
  if (!entries.length) {
    return null;
  }

  const openEntries = entries.filter((entry) => entry.open);
  const pool = openEntries.length ? openEntries : entries;

  return pool
    .slice()
    .sort((left, right) => right.ts - left.ts || left.path.localeCompare(right.path))[0];
}

function resolveVaultForDeploy() {
  const explicitVault = process.env.VAULT_PATH?.trim();
  if (explicitVault) {
    return {
      vaultPath: path.resolve(explicitVault),
      source: "env",
      detail: "Resolved from VAULT_PATH.",
    };
  }

  const configPath = findObsidianConfigPath();
  const preferredVault = pickPreferredVault(loadVaultEntries(configPath));
  if (preferredVault) {
    return {
      vaultPath: preferredVault.path,
      source: preferredVault.open ? "obsidian-open" : "obsidian-recent",
      detail: preferredVault.open
        ? `Resolved from open vault in ${configPath}.`
        : `Resolved from most recently used vault in ${configPath}.`,
    };
  }

  return {
    vaultPath: DEFAULT_VAULT,
    source: "default",
    detail: `Fell back to DEFAULT_VAULT because no Obsidian vault metadata was available.`,
  };
}

module.exports = {
  DEFAULT_VAULT,
  findObsidianConfigPath,
  loadVaultEntries,
  pickPreferredVault,
  resolveVaultForDeploy,
};
