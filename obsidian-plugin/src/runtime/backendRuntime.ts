import {
  execFile,
  spawn,
  type ChildProcessWithoutNullStreams,
} from "node:child_process";
import {
  chmodSync,
  appendFileSync,
  createWriteStream,
  existsSync,
  mkdirSync,
  readFileSync,
  writeFileSync,
} from "node:fs";
import { createServer } from "node:net";
import { dirname, join, resolve } from "node:path";
import { createHash, randomBytes } from "node:crypto";

import { App, FileSystemAdapter, Platform } from "obsidian";

import { AgentClient } from "../api/client";
import {
  DEFAULT_DIARY_SETTINGS,
  DIARY_PERIODS,
  normalizeDiarySettings,
  writeDiarySettingsFile,
} from "../config/diaryConfig";
import type { CrabbySettings } from "../settings";
import {
  ADMIN_RELOAD_HEADER,
  isTruthyEnvValue,
  readEnvValue,
  upsertEnvFile,
} from "../config/backendConfig";
import {
  DEFAULT_PROMPT_TEMPLATES,
  seedDirectoryIfEmpty,
  seedOrMigrateDefaultPersonas,
} from "./defaultConfigTemplates";
import {
  migrateRuntimeDataDirectories,
  type RuntimeDataMigration,
} from "./runtimeDataMigration";
import {
  resolveRuntimeExecutablePath,
  serializeRuntimeExecutablePath,
} from "./runtimeState";

const PLUGIN_ID = "crabby";
const DEFAULT_HOST = "127.0.0.1";
const DEFAULT_PORT = 8000;
const HEALTH_TIMEOUT_MS = 15000;
const SHUTDOWN_TIMEOUT_MS = 2500;
const EXISTING_BACKEND_TIMEOUT_MS = 1200;
const HOST_HEARTBEAT_INTERVAL_MS = 5000;
// Obsidian plugin timers run in Electron's renderer and can be throttled while
// the window is backgrounded, commonly to about one tick per minute.
const HOST_HEARTBEAT_TIMEOUT_SECONDS = 180;
const MEMORY_TYPES = ["user", "feedback", "project", "reference"] as const;
const MEMORY_OPERATING_RULES = `# Memory Operating Rules

- Use \`memory_search(mode="list_registry")\` before writing new memories.
- Prefer existing topics and domains from \`REGISTRY.md\` when they match.
- Recall project, feedback, and reference memories from the current topic first.
- Recall global constraints from \`type=user|feedback, topic=general\`.
- Use domains for cross-topic recall; read \`state=active\` memories by default.
- More specific feedback overrides general feedback.

# Hot Entries

- Current focus: general
- Common global topic: general
`;
const MEMORY_REGISTRY = `# Memory Registry

## Topics

- general

## Domains

`;
const LEGACY_DIARY_TEMPLATE = `---
date: {{date}}
---

# {{date}} 日记

## 今日要点

{{summary}}

## 涉及主题

{{topics}}

## 关联记忆

(由 agent 在写入时填入相关 memory 文件链接)
`;
const DIARY_TEMPLATE_CONTENTS: Record<string, string> = {
  daily: `---
period: daily
date: {{date}}
---

# {{date}} 日记

## 今日要点

{{summary}}

## 涉及主题

{{topics}}

## 涉及领域

{{domains}}

## 关联记忆

{{memory_links}}

## 条目

{{entries}}
`,
  weekly: `---
period: weekly
period_start: {{period_start}}
period_end: {{period_end}}
---

# {{period_start}} ~ {{period_end}} 周记

{{entries}}
`,
  monthly: `---
period: monthly
period_start: {{period_start}}
period_end: {{period_end}}
---

# {{period_start}} ~ {{period_end}} 月记

{{entries}}
`,
  quarterly: `---
period: quarterly
period_start: {{period_start}}
period_end: {{period_end}}
---

# {{period_start}} ~ {{period_end}} 季度记录

{{entries}}
`,
  yearly: `---
period: yearly
period_start: {{period_start}}
period_end: {{period_end}}
---

# {{period_start}} ~ {{period_end}} 年记录

{{entries}}
`,
};

export interface RuntimeLayout {
  pluginDir: string;
  userDataDir: string;
  configDir: string;
  envPath: string;
  mcpConfigPath: string;
  promptsDir: string;
  personasDir: string;
  memoryDir: string;
  templatesDir: string;
  dataDir: string;
  sessionsDir: string;
  attachmentsDir: string;
  logsDir: string;
  runtimeDir: string;
  statePath: string;
  heartbeatPath: string;
  devRuntimePath: string;
}

export interface DevRuntimeConfig {
  mode: "dev";
  repoRoot: string;
  backendCommand: string;
  backendArgs: string[];
  backendCwd: string;
}

export interface RuntimeAsset {
  url: string;
  sha256: string;
  executableName?: string;
}

export interface RuntimeManifest {
  version: string;
  platforms: Partial<Record<NodeJS.Platform, RuntimeAsset>>;
}

export interface RuntimeState {
  mode: "dev" | "production";
  version?: string;
  platform?: NodeJS.Platform;
  executablePath?: string;
  port?: number;
  pid?: number;
  startedAt?: string;
}

export interface RuntimeStatus {
  mode: "dev" | "production";
  version: string;
  installed: boolean;
  running: boolean;
  backendUrl: string;
  port: number | null;
  pid: number | null;
  envPath: string;
  mcpConfigPath: string;
  promptsDir: string;
  personasDir: string;
  memoryDir: string;
  templatesDir: string;
  dataDir: string;
  logsDir: string;
  detail: string;
}

interface LaunchConfig {
  mode: "dev" | "production";
  command: string;
  args: string[];
  cwd: string;
  version?: string;
}

interface ExistingBackend {
  backendUrl: string;
  port: number;
  pid: number | null;
}

export function resolvePluginRuntimeLayout(app: App): RuntimeLayout {
  if (!Platform.isDesktopApp) {
    throw new Error("Crabby 本地后端程序需要 Obsidian 桌面版。");
  }

  const adapter = app.vault.adapter;
  if (!(adapter instanceof FileSystemAdapter)) {
    throw new Error("无法解析桌面端 vault 文件系统路径。");
  }

  const vaultBasePath = adapter.getBasePath();
  const pluginDir = join(vaultBasePath, app.vault.configDir, "plugins", PLUGIN_ID);
  const userDataDir = join(vaultBasePath, ".crabby");
  const configDir = join(userDataDir, "config");
  const dataDir = join(userDataDir, "data");
  const logsDir = join(userDataDir, "logs");
  const memoryDir = join(userDataDir, "memory");
  const templatesDir = join(userDataDir, "templates");
  const runtimeDir = join(pluginDir, "runtime");

  return {
    pluginDir,
    userDataDir,
    configDir,
    envPath: join(configDir, ".env"),
    mcpConfigPath: join(configDir, "mcp_servers.json"),
    promptsDir: join(configDir, "prompts"),
    personasDir: join(configDir, "personas"),
    memoryDir,
    templatesDir,
    dataDir,
    sessionsDir: join(dataDir, "sessions"),
    attachmentsDir: join(dataDir, "attachments"),
    logsDir,
    runtimeDir,
    statePath: join(runtimeDir, "state.json"),
    heartbeatPath: join(runtimeDir, "host-heartbeat.json"),
    devRuntimePath: join(pluginDir, ".dev-runtime.json"),
  };
}

export class BackendRuntimeManager {
  private child: ChildProcessWithoutNullStreams | null = null;
  private externalBackend: ExistingBackend | null = null;
  private heartbeatTimer: ReturnType<typeof setInterval> | null = null;
  private layout: RuntimeLayout;
  private statusDetail = "本地后端程序尚未启动。";

  constructor(
    private app: App,
    private settings: CrabbySettings,
  ) {
    this.layout = resolvePluginRuntimeLayout(app);
  }

  getLayout(): RuntimeLayout {
    return this.layout;
  }

  async ensureRuntimeLayout(): Promise<RuntimeLayout> {
    this.migrateLegacyRuntimeData();

    for (const path of [
      this.layout.userDataDir,
      this.layout.configDir,
      this.layout.promptsDir,
      this.layout.personasDir,
      this.layout.memoryDir,
      this.layout.templatesDir,
      this.layout.sessionsDir,
      this.layout.attachmentsDir,
      this.layout.logsDir,
      this.layout.runtimeDir,
      dirname(this.layout.statePath),
    ]) {
      mkdirSync(path, { recursive: true });
    }
    this.ensureMemoryLayout();
    const diarySync = this.syncDiaryConfig();
    if (!diarySync.ok) {
      this.appendRuntimeLog(`failed to sync diary config: ${diarySync.message}`);
    }

    const token = this.ensureAdminToken();
    upsertEnvFile(this.layout.envPath, {
      CRABBY_ADMIN_ENABLED: "true",
      CRABBY_ADMIN_TOKEN: token,
      ...this.getHostWatchdogEnv(),
      CRABBY_BACKEND_RELOADER_PARENT: "false",
      VAULT_PATH: this.getVaultBasePath(),
      HOST: DEFAULT_HOST,
      PROMPTS_DIR: this.layout.promptsDir,
      PERSONAS_DIR: this.layout.personasDir,
    });
    this.startHostHeartbeat();

    const seededPrompts = seedDirectoryIfEmpty(
      this.layout.promptsDir,
      DEFAULT_PROMPT_TEMPLATES,
    );
    const personaSeed = seedOrMigrateDefaultPersonas(this.layout.personasDir);
    if (seededPrompts) {
      this.appendRuntimeLog("seeded default prompt templates");
    }
    if (personaSeed.seeded) {
      this.appendRuntimeLog("seeded default persona templates");
    }
    if (personaSeed.migrated) {
      this.appendRuntimeLog("migrated legacy default persona templates");
    }

    if (!existsSync(this.layout.mcpConfigPath)) {
      writeFileSync(
        this.layout.mcpConfigPath,
        `${JSON.stringify({ mcpServers: {} }, null, 2)}\n`,
        "utf8",
      );
    }

    this.settings.backendEnvPath = this.layout.envPath;
    this.settings.backendMcpConfigPath = this.layout.mcpConfigPath;
    this.settings.backendPath = "";
    this.appendRuntimeLog("runtime layout ensured");
    return this.layout;
  }

  async start(): Promise<RuntimeStatus> {
    await this.ensureRuntimeLayout();
    this.appendRuntimeLog("start requested");
    if (this.child && !this.child.killed) {
      this.appendRuntimeLog(`start skipped because child is already running: pid=${this.child.pid ?? "unknown"}`);
      return this.getStatus();
    }
    if (this.externalBackend) {
      const token = this.ensureAdminToken();
      if (await isManagedBackendReachable(this.externalBackend.backendUrl, token)) {
        this.appendRuntimeLog(
          `start skipped because existing backend is reachable: ${this.externalBackend.backendUrl}`,
        );
        return this.getStatus();
      }
      this.appendRuntimeLog(
        `discarding unreachable existing backend: ${this.externalBackend.backendUrl}`,
      );
      this.externalBackend = null;
    }

    const launch = this.resolveLaunchConfig();
    if (!launch) {
      this.statusDetail = "正式版后端程序尚未安装。";
      this.appendRuntimeLog("start aborted: no launch config");
      return this.getStatus();
    }

    const reusedStatus = await this.reuseExistingBackendIfAvailable(launch);
    if (reusedStatus) {
      return reusedStatus;
    }

    const port = await findAvailablePort(DEFAULT_PORT);
    const backendUrl = `http://${DEFAULT_HOST}:${port}`;
    const launchArgs =
      launch.mode === "dev"
        ? withDevHostPortArgs(launch.args, DEFAULT_HOST, port)
        : launch.args;
    const reloaderParentValue = getReloaderParentValue(launchArgs);
    this.appendRuntimeLog(
      `launch config resolved: mode=${launch.mode} command=${launch.command} args=${JSON.stringify(launch.args)} cwd=${launch.cwd} port=${port}`,
    );
    const adminToken = this.ensureAdminToken();
    upsertEnvFile(this.layout.envPath, {
      CRABBY_ADMIN_ENABLED: "true",
      CRABBY_ADMIN_TOKEN: adminToken,
      ...this.getHostWatchdogEnv(),
      CRABBY_BACKEND_RELOADER_PARENT: reloaderParentValue,
      VAULT_PATH: this.getVaultBasePath(),
      HOST: DEFAULT_HOST,
      PORT: String(port),
      PROMPTS_DIR: this.layout.promptsDir,
      PERSONAS_DIR: this.layout.personasDir,
    });

    const out = createWriteStream(join(this.layout.logsDir, "backend-out.log"), {
      flags: "a",
    });
    const err = createWriteStream(join(this.layout.logsDir, "backend-error.log"), {
      flags: "a",
    });

    const env: NodeJS.ProcessEnv = {
      ...process.env,
      VAULT_PATH: this.getVaultBasePath(),
      MCP_CONFIG_FILE: this.layout.mcpConfigPath,
      DATA_DIR: this.layout.dataDir,
      LOG_DIR: this.layout.logsDir,
      ...this.getHostWatchdogEnv(),
      CRABBY_BACKEND_RELOADER_PARENT: reloaderParentValue,
      HOST: DEFAULT_HOST,
      PORT: String(port),
      PROMPTS_DIR: this.layout.promptsDir,
      PERSONAS_DIR: this.layout.personasDir,
      PYTHONUNBUFFERED: "1",
      PYTHONIOENCODING: "utf-8",
    };
    const pathKey = getPathEnvKey(env);
    env[pathKey] = buildRuntimePath(env[pathKey]);

    this.appendRuntimeLog(`spawning backend: ${launch.command} ${launchArgs.join(" ")}`);
    try {
      this.child = spawn(launch.command, launchArgs, {
        cwd: launch.cwd,
        env,
        windowsHide: true,
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      this.statusDetail = `后端进程启动失败：${message}`;
      this.appendRuntimeLog(`spawn threw synchronously: ${message}`);
      out.end();
      err.end();
      return this.getStatus();
    }
    this.child.stdout.pipe(out);
    this.child.stderr.pipe(err);
    this.child.once("error", (error) => {
      this.statusDetail = `后端进程启动失败：${error.message}`;
      this.appendRuntimeLog(`child error: ${error.message}`);
      this.child = null;
      out.end();
      err.end();
    });
    this.child.once("exit", (code, signal) => {
      this.statusDetail = `后端进程已退出，退出码 ${code ?? "null"}，信号 ${signal ?? "null"}。`;
      this.appendRuntimeLog(`child exited: code=${code ?? "null"} signal=${signal ?? "null"}`);
      this.child = null;
      out.end();
      err.end();
    });

    this.settings.backendUrl = backendUrl;
    this.writeState({
      mode: launch.mode,
      version: launch.version,
      platform: process.platform,
      executablePath: launch.command,
      port,
      pid: this.child.pid,
      startedAt: new Date().toISOString(),
    });

    try {
      await waitForHealth(backendUrl, HEALTH_TIMEOUT_MS);
      this.statusDetail = `后端正在以${launch.mode === "dev" ? "开发版" : "正式版"}运行。`;
      this.appendRuntimeLog(`health check passed: ${backendUrl}`);
    } catch (error) {
      this.statusDetail =
        error instanceof Error ? error.message : "后端健康检查失败。";
      this.appendRuntimeLog(`health check failed: ${this.statusDetail}`);
    }
    return this.getStatus();
  }

  async stop(): Promise<RuntimeStatus> {
    this.stopHostHeartbeat();
    const child = this.child;
    if (!child || child.killed) {
      return this.stopExistingBackendWithoutChild();
    }

    const token = this.ensureAdminToken();
    const backendUrl = this.settings.backendUrl;
    try {
      await requestBackendShutdown(backendUrl, token);
      await waitForExit(child, SHUTDOWN_TIMEOUT_MS);
    } catch {
      await killProcessTree(child);
    }

    this.child = null;
    this.statusDetail = "本地后端程序已停止。";
    return this.getStatus();
  }

  async restart(): Promise<RuntimeStatus> {
    await this.stop();
    return this.start();
  }

  async installRuntime(manifestUrl: string): Promise<RuntimeStatus> {
    await this.ensureRuntimeLayout();
    const normalizedUrl = manifestUrl.trim();
    if (!normalizedUrl) {
      throw new Error("尚未配置后端程序下载清单 URL。");
    }

    const manifestResp = await fetch(normalizedUrl);
    if (!manifestResp.ok) {
      throw new Error(`后端程序下载清单获取失败：HTTP ${manifestResp.status}`);
    }
    const manifest = (await manifestResp.json()) as RuntimeManifest;
    const asset = manifest.platforms?.[process.platform];
    if (!asset) {
      throw new Error(`当前平台没有可用的本地后端程序：${process.platform}。`);
    }

    const assetResp = await fetch(asset.url);
    if (!assetResp.ok) {
      throw new Error(`本地后端程序下载失败：HTTP ${assetResp.status}`);
    }
    const bytes = Buffer.from(await assetResp.arrayBuffer());
    const actualHash = createHash("sha256").update(bytes).digest("hex");
    if (actualHash.toLowerCase() !== asset.sha256.toLowerCase()) {
      throw new Error("本地后端程序 SHA256 校验失败。");
    }

    const executableName =
      asset.executableName ?? (process.platform === "win32" ? "crabby-backend.exe" : "crabby-backend");
    const installDir = join(
      this.layout.runtimeDir,
      "backend",
      manifest.version,
      process.platform,
    );
    mkdirSync(installDir, { recursive: true });
    const executablePath = join(installDir, executableName);
    writeFileSync(executablePath, bytes);
    if (process.platform !== "win32") {
      chmodSync(executablePath, 0o755);
    }

    this.writeState({
      mode: "production",
      version: manifest.version,
      platform: process.platform,
      executablePath,
    });
    this.statusDetail = `已安装本地后端程序 ${manifest.version}。`;
    return this.getStatus();
  }

  getStatus(): RuntimeStatus {
    const state = this.readState();
    const devConfig = this.readDevRuntimeConfig();
    const mode = devConfig ? "dev" : "production";
    const port =
      this.externalBackend?.port ??
      parseBackendPort(this.settings.backendUrl) ??
      state?.port ??
      null;
    const running =
      Boolean(this.child && !this.child.killed) || Boolean(this.externalBackend);
    const version =
      mode === "dev" ? (state?.version?.trim() || "dev") : (state?.version?.trim() || "-");
    return {
      mode,
      version,
      installed: Boolean(devConfig || state?.executablePath),
      running,
      backendUrl:
        port !== null ? `http://${DEFAULT_HOST}:${port}` : this.settings.backendUrl,
      port,
      pid: running ? (this.child?.pid ?? this.externalBackend?.pid ?? null) : null,
      envPath: this.layout.envPath,
      mcpConfigPath: this.layout.mcpConfigPath,
      promptsDir: this.layout.promptsDir,
      personasDir: this.layout.personasDir,
      memoryDir: this.layout.memoryDir,
      templatesDir: this.layout.templatesDir,
      dataDir: this.layout.dataDir,
      logsDir: this.layout.logsDir,
      detail: this.statusDetail,
    };
  }

  private resolveLaunchConfig(): LaunchConfig | null {
    const devConfig = this.readDevRuntimeConfig();
    if (devConfig) {
      return {
        mode: "dev",
        command: devConfig.backendCommand,
        args: devConfig.backendArgs,
        cwd: devConfig.backendCwd,
      };
    }

    const state = this.readState();
    const executablePath =
      state?.mode === "production"
        ? resolveRuntimeExecutablePath(this.layout.runtimeDir, state.executablePath)
        : null;
    if (state?.mode === "production" && executablePath && existsSync(executablePath)) {
      return {
        mode: "production",
        command: executablePath,
        args: [],
        cwd: dirname(executablePath),
        version: state.version,
      };
    }

    return null;
  }

  private async reuseExistingBackendIfAvailable(
    launch: LaunchConfig,
  ): Promise<RuntimeStatus | null> {
    const token = this.ensureAdminToken();
    const existingBackend = await this.findExistingManagedBackend(token);
    if (!existingBackend) {
      return null;
    }

    this.externalBackend = existingBackend;
    this.settings.backendUrl = existingBackend.backendUrl;
    this.startHostHeartbeat();
    const launchArgs =
      launch.mode === "dev"
        ? withDevHostPortArgs(launch.args, DEFAULT_HOST, existingBackend.port)
        : launch.args;
    upsertEnvFile(this.layout.envPath, {
      CRABBY_ADMIN_ENABLED: "true",
      CRABBY_ADMIN_TOKEN: token,
      ...this.getHostWatchdogEnv(),
      CRABBY_BACKEND_RELOADER_PARENT: getReloaderParentValue(launchArgs),
      VAULT_PATH: this.getVaultBasePath(),
      HOST: DEFAULT_HOST,
      PORT: String(existingBackend.port),
      PROMPTS_DIR: this.layout.promptsDir,
      PERSONAS_DIR: this.layout.personasDir,
    });
    this.writeState({
      mode: launch.mode,
      version: launch.version,
      platform: process.platform,
      executablePath: launch.command,
      port: existingBackend.port,
      pid: existingBackend.pid ?? undefined,
      startedAt: new Date().toISOString(),
    });
    this.statusDetail = "Backend already running; reusing existing managed process.";
    this.appendRuntimeLog(
      `reusing existing backend: ${existingBackend.backendUrl} pid=${existingBackend.pid ?? "unknown"}`,
    );
    return this.getStatus();
  }

  private async stopExistingBackendWithoutChild(): Promise<RuntimeStatus> {
    this.child = null;
    const token = this.ensureAdminToken();
    const existingBackend =
      this.externalBackend ?? (await this.findExistingManagedBackend(token));
    if (!existingBackend) {
      this.externalBackend = null;
      this.statusDetail = "本地后端程序当前未运行。";
      return this.getStatus();
    }

    try {
      await requestBackendShutdown(existingBackend.backendUrl, token);
      await waitForBackendUnavailable(
        existingBackend.backendUrl,
        SHUTDOWN_TIMEOUT_MS,
      );
      this.appendRuntimeLog(
        `shutdown requested for existing backend: ${existingBackend.backendUrl}`,
      );
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      this.appendRuntimeLog(
        `failed to stop existing backend ${existingBackend.backendUrl}: ${message}`,
      );
      if (await isManagedBackendReachable(existingBackend.backendUrl, token)) {
        this.externalBackend = existingBackend;
        this.statusDetail = `Backend shutdown failed: ${message}`;
        return this.getStatus();
      }
    }

    this.externalBackend = null;
    this.statusDetail = "本地后端程序已停止。";
    return this.getStatus();
  }

  private async findExistingManagedBackend(
    token: string,
  ): Promise<ExistingBackend | null> {
    const state = this.readState();
    for (const port of uniquePorts([
      parseBackendPort(this.settings.backendUrl),
      state?.port ?? null,
      DEFAULT_PORT,
    ])) {
      const backendUrl = `http://${DEFAULT_HOST}:${port}`;
      if (await isManagedBackendReachable(backendUrl, token)) {
        return {
          backendUrl,
          port,
          pid: state?.port === port ? (state.pid ?? null) : null,
        };
      }
    }
    return null;
  }

  private readDevRuntimeConfig(): DevRuntimeConfig | null {
    if (!existsSync(this.layout.devRuntimePath)) {
      return null;
    }
    try {
      const parsed = JSON.parse(stripJsonBom(readFileSync(this.layout.devRuntimePath, "utf8")));
      if (
        parsed?.mode === "dev" &&
        typeof parsed.backendCommand === "string" &&
        Array.isArray(parsed.backendArgs) &&
        typeof parsed.backendCwd === "string"
      ) {
        return {
          mode: "dev",
          repoRoot: resolve(String(parsed.repoRoot ?? "")),
          backendCommand: resolve(parsed.backendCommand),
          backendArgs: parsed.backendArgs.map(String),
          backendCwd: resolve(parsed.backendCwd),
        };
      }
    } catch {
      return null;
    }
    return null;
  }

  private readState(): RuntimeState | null {
    if (!existsSync(this.layout.statePath)) {
      return null;
    }
    try {
      return JSON.parse(stripJsonBom(readFileSync(this.layout.statePath, "utf8"))) as RuntimeState;
    } catch {
      return null;
    }
  }

  private writeState(state: RuntimeState): void {
    mkdirSync(dirname(this.layout.statePath), { recursive: true });
    const nextState = this.normalizeRuntimeStateForWrite(state);
    writeFileSync(
      this.layout.statePath,
      `${JSON.stringify(nextState, null, 2)}\n`,
      "utf8",
    );
  }

  private normalizeRuntimeStateForWrite(state: RuntimeState): RuntimeState {
    if (state.mode !== "production" || !state.executablePath) {
      return state;
    }

    return {
      ...state,
      executablePath: serializeRuntimeExecutablePath(
        this.layout.runtimeDir,
        state.executablePath,
      ),
    };
  }

  private migrateLegacyRuntimeData(): void {
    const legacyPluginDir = this.layout.pluginDir;
    const migrations: RuntimeDataMigration[] = [
      {
        label: "config",
        legacyPath: join(legacyPluginDir, "config"),
        targetPath: this.layout.configDir,
      },
      {
        label: "data",
        legacyPath: join(legacyPluginDir, "data"),
        targetPath: this.layout.dataDir,
      },
      {
        label: "logs",
        legacyPath: join(legacyPluginDir, "logs"),
        targetPath: this.layout.logsDir,
      },
    ];

    for (const migration of migrateRuntimeDataDirectories(migrations)) {
      if (migration.status === "missing") {
        continue;
      }

      this.appendRuntimeLog(
        [
          `legacy ${migration.label} migration: ${migration.status}`,
          `from=${migration.legacyPath}`,
          `to=${migration.targetPath}`,
          `moved=${migration.movedEntries}`,
          `skipped=${migration.skippedEntries}`,
          `message=${migration.message}`,
        ].join(" "),
      );
    }
  }

  private appendRuntimeLog(message: string): void {
    try {
      mkdirSync(this.layout.logsDir, { recursive: true });
      appendFileSync(
        join(this.layout.logsDir, "runtime-manager.log"),
        `${new Date().toISOString()} ${message}\n`,
        "utf8",
      );
    } catch {
      // Logging must not block runtime startup.
    }
  }

  private getHostWatchdogEnv(): Record<string, string> {
    return {
      CRABBY_HOST_HEARTBEAT_FILE: this.layout.heartbeatPath,
      CRABBY_HOST_HEARTBEAT_TIMEOUT_SECONDS: String(
        HOST_HEARTBEAT_TIMEOUT_SECONDS,
      ),
      CRABBY_HOST_PID: String(process.pid),
    };
  }

  private startHostHeartbeat(): void {
    if (this.heartbeatTimer) {
      return;
    }

    this.writeHostHeartbeat();
    this.heartbeatTimer = setInterval(
      () => this.writeHostHeartbeat(),
      HOST_HEARTBEAT_INTERVAL_MS,
    );
    this.heartbeatTimer.unref?.();
  }

  private stopHostHeartbeat(): void {
    if (!this.heartbeatTimer) {
      return;
    }

    clearInterval(this.heartbeatTimer);
    this.heartbeatTimer = null;
  }

  private writeHostHeartbeat(): void {
    try {
      mkdirSync(dirname(this.layout.heartbeatPath), { recursive: true });
      writeFileSync(
        this.layout.heartbeatPath,
        `${JSON.stringify(
          {
            pid: process.pid,
            updatedAt: new Date().toISOString(),
            pluginDir: this.layout.pluginDir,
          },
          null,
          2,
        )}\n`,
        "utf8",
      );
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      this.appendRuntimeLog(`failed to write host heartbeat: ${message}`);
    }
  }

  private ensureMemoryLayout(): void {
    for (const memoryType of MEMORY_TYPES) {
      mkdirSync(join(this.layout.memoryDir, memoryType), { recursive: true });
    }
    this.writeFileIfMissing(join(this.layout.memoryDir, "MEMORY.md"), MEMORY_OPERATING_RULES);
    this.writeFileIfMissing(join(this.layout.memoryDir, "REGISTRY.md"), MEMORY_REGISTRY);
    this.ensureDiaryTemplates();
  }

  public syncDiaryConfig(): { ok: boolean; message: string } {
    const diaryConfigPath = join(this.layout.configDir, "diary.json");
    try {
      const normalized = normalizeDiarySettings(
        this.settings.diary ?? DEFAULT_DIARY_SETTINGS,
      );
      this.settings.diary = normalized;
      writeDiarySettingsFile(diaryConfigPath, normalized);
      return { ok: true, message: "Diary config synced." };
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      return { ok: false, message };
    }
  }

  private ensureDiaryTemplates(): void {
    const legacyDiaryTemplatePath = join(this.layout.templatesDir, "diary.md");
    const diaryTemplatesDir = join(this.layout.templatesDir, "diary");
    const legacyExistsBefore = existsSync(legacyDiaryTemplatePath);

    this.writeFileIfMissing(legacyDiaryTemplatePath, LEGACY_DIARY_TEMPLATE);
    mkdirSync(diaryTemplatesDir, { recursive: true });

    for (const period of DIARY_PERIODS) {
      const relativePath = join(diaryTemplatesDir, `${period}.md`);
      if (period === "daily" && !existsSync(relativePath) && legacyExistsBefore) {
        const legacyText = readFileSync(legacyDiaryTemplatePath, "utf8");
        this.writeFileIfMissing(relativePath, legacyText);
        continue;
      }
      this.writeFileIfMissing(relativePath, DIARY_TEMPLATE_CONTENTS[period]);
    }
  }

  private writeFileIfMissing(path: string, content: string): void {
    if (existsSync(path)) {
      return;
    }
    mkdirSync(dirname(path), { recursive: true });
    writeFileSync(path, content, "utf8");
  }

  private ensureAdminToken(): string {
    const existingEnabled = readEnvValue(this.layout.envPath, "CRABBY_ADMIN_ENABLED");
    const existingToken = readEnvValue(this.layout.envPath, "CRABBY_ADMIN_TOKEN");
    const token = existingToken?.trim() || randomBytes(24).toString("hex");
    if (!isTruthyEnvValue(existingEnabled) || !existingToken) {
      upsertEnvFile(this.layout.envPath, {
        CRABBY_ADMIN_ENABLED: "true",
        CRABBY_ADMIN_TOKEN: token,
      });
    }
    return token;
  }

  private getVaultBasePath(): string {
    const adapter = this.app.vault.adapter;
    if (adapter instanceof FileSystemAdapter) {
      return adapter.getBasePath();
    }
    return "";
  }
}

function uniquePorts(values: Array<number | null | undefined>): number[] {
  const ports: number[] = [];
  const seen = new Set<number>();
  for (const value of values) {
    if (
      typeof value !== "number" ||
      !Number.isInteger(value) ||
      value <= 0 ||
      value > 65535 ||
      seen.has(value)
    ) {
      continue;
    }
    seen.add(value);
    ports.push(value);
  }
  return ports;
}

async function isManagedBackendReachable(
  backendUrl: string,
  adminToken: string,
): Promise<boolean> {
  if (!(await fetchOkWithTimeout(`${backendUrl}/health`, {}, EXISTING_BACKEND_TIMEOUT_MS))) {
    return false;
  }
  const hasManagedAdminPlane = await fetchOkWithTimeout(
    `${backendUrl}/admin/mcp/status`,
    {
      headers: { [ADMIN_RELOAD_HEADER]: adminToken },
    },
    EXISTING_BACKEND_TIMEOUT_MS,
  );
  if (!hasManagedAdminPlane) {
    return false;
  }

  return fetchOkWithTimeout(
    `${backendUrl}/admin/profiles`,
    {
      headers: { [ADMIN_RELOAD_HEADER]: adminToken },
    },
    EXISTING_BACKEND_TIMEOUT_MS,
  );
}

async function fetchOkWithTimeout(
  url: string,
  init: RequestInit,
  timeoutMs: number,
): Promise<boolean> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const resp = await fetch(url, {
      ...init,
      signal: controller.signal,
    });
    return resp.ok;
  } catch {
    return false;
  } finally {
    clearTimeout(timer);
  }
}

async function requestBackendShutdown(
  backendUrl: string,
  adminToken: string,
): Promise<void> {
  const resp = await fetch(`${backendUrl}/admin/shutdown`, {
    method: "POST",
    headers: { [ADMIN_RELOAD_HEADER]: adminToken },
  });
  if (!resp.ok) {
    throw new Error(`Backend shutdown failed: HTTP ${resp.status}`);
  }
}

async function findAvailablePort(startPort: number): Promise<number> {
  for (let port = startPort; port < startPort + 100; port += 1) {
    if (await canListen(port)) {
      return port;
    }
  }
  throw new Error(`从端口 ${startPort} 开始没有找到可用的后端端口。`);
}

function canListen(port: number): Promise<boolean> {
  return new Promise((resolvePromise) => {
    const server = createServer();
    server.once("error", () => resolvePromise(false));
    server.once("listening", () => {
      server.close(() => resolvePromise(true));
    });
    server.listen(port, DEFAULT_HOST);
  });
}

function withDevHostPortArgs(
  args: string[],
  host: string,
  port: number,
): string[] {
  const nextArgs = [...args];
  if (!hasCliOption(nextArgs, "--host")) {
    nextArgs.push("--host", host);
  }
  if (!hasCliOption(nextArgs, "--port")) {
    nextArgs.push("--port", String(port));
  }
  return nextArgs;
}

function hasCliOption(args: string[], option: string): boolean {
  return args.some((arg) => arg === option || arg.startsWith(`${option}=`));
}

function getReloaderParentValue(args: string[]): string {
  return hasCliOption(args, "--reload") ? "true" : "false";
}

function getPathEnvKey(env: NodeJS.ProcessEnv): string {
  return Object.keys(env).find((key) => key.toLowerCase() === "path") ?? "PATH";
}

function buildRuntimePath(currentPath: string | undefined): string {
  const delimiter = process.platform === "win32" ? ";" : ":";
  const entries = new Set(
    (currentPath ?? "")
      .split(delimiter)
      .map((entry) => entry.trim())
      .filter(Boolean),
  );

  for (const candidate of getRuntimePathCandidates()) {
    if (existsSync(candidate)) {
      entries.add(candidate);
    }
  }

  return Array.from(entries).join(delimiter);
}

function getRuntimePathCandidates(): string[] {
  if (process.platform !== "win32") {
    return [];
  }

  const userProfile = process.env.USERPROFILE?.trim();
  const localAppData = process.env.LOCALAPPDATA?.trim();
  const appData = process.env.APPDATA?.trim();
  return [
    userProfile ? join(userProfile, ".local", "bin") : "",
    localAppData ? join(localAppData, "Microsoft", "WindowsApps") : "",
    appData ? join(appData, "Python", "Python312", "Scripts") : "",
    localAppData ? join(localAppData, "Programs", "Python", "Python312", "Scripts") : "",
  ].filter(Boolean);
}

function stripJsonBom(content: string): string {
  return content.charCodeAt(0) === 0xfeff ? content.slice(1) : content;
}

async function waitForHealth(baseUrl: string, timeoutMs: number): Promise<void> {
  const startedAt = Date.now();
  const client = new AgentClient(baseUrl);
  while (Date.now() - startedAt < timeoutMs) {
    if (await client.health()) {
      return;
    }
    await sleep(250);
  }
  throw new Error(`后端在 ${timeoutMs}ms 内没有通过健康检查。`);
}

async function waitForBackendUnavailable(
  baseUrl: string,
  timeoutMs: number,
): Promise<void> {
  const startedAt = Date.now();
  const client = new AgentClient(baseUrl);
  while (Date.now() - startedAt < timeoutMs) {
    if (!(await client.health())) {
      return;
    }
    await sleep(250);
  }
  throw new Error(`Backend did not stop within ${timeoutMs}ms.`);
}

function waitForExit(
  child: ChildProcessWithoutNullStreams,
  timeoutMs: number,
): Promise<void> {
  if (child.exitCode !== null || child.signalCode !== null) {
    return Promise.resolve();
  }
  return new Promise((resolvePromise, rejectPromise) => {
    const timer = setTimeout(() => rejectPromise(new Error("后端关闭超时。")), timeoutMs);
    child.once("exit", () => {
      clearTimeout(timer);
      resolvePromise();
    });
  });
}

async function killProcessTree(child: ChildProcessWithoutNullStreams): Promise<void> {
  if (child.exitCode !== null || child.signalCode !== null || child.killed) {
    return;
  }

  if (process.platform === "win32" && child.pid) {
    await new Promise<void>((resolvePromise) => {
      execFile(
        "taskkill.exe",
        ["/PID", String(child.pid), "/T", "/F"],
        { windowsHide: true },
        () => resolvePromise(),
      );
    });
    return;
  }

  child.kill("SIGTERM");
  try {
    await waitForExit(child, 1000);
  } catch {
    if (!child.killed) {
      child.kill("SIGKILL");
    }
  }
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolvePromise) => setTimeout(resolvePromise, ms));
}

function parseBackendPort(url: string): number | null {
  try {
    const parsed = new URL(url);
    if (!parsed.port) {
      return parsed.protocol === "https:" ? 443 : 80;
    }
    return Number.parseInt(parsed.port, 10);
  } catch {
    return null;
  }
}
