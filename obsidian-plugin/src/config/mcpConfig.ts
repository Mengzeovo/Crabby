import {
  copyFileSync,
  existsSync,
  mkdirSync,
  readFileSync,
  writeFileSync,
} from "node:fs";
import { dirname, join, resolve } from "node:path";

import type {
  AgentClient,
  MCPRuntimeStatus,
  ReloadConfigResult,
} from "../api/client";
import type { LifeAssistantSettings } from "../settings";
import {
  isTruthyEnvValue,
  readEnvValue,
  resolveBackendEnvPath,
} from "./backendConfig";

const ADMIN_ENABLED_KEY = "LIFE_ASSISTANT_ADMIN_ENABLED";
const ADMIN_TOKEN_KEY = "LIFE_ASSISTANT_ADMIN_TOKEN";

export interface BackendMcpPathResolution {
  ok: boolean;
  configPath?: string;
  examplePath?: string;
  derivedFromBackendEnvPath: boolean;
  message: string;
}

export interface McpConfigValidationResult {
  ok: boolean;
  message: string;
  serverNames: string[];
}

export interface LocalMcpConfigResult {
  ok: boolean;
  message: string;
  configPath?: string;
  examplePath?: string;
  text?: string;
  exists?: boolean;
  reloadStatus?: number | null;
}

export interface McpRuntimeStatusResult {
  ok: boolean;
  message: string;
  status?: MCPRuntimeStatus;
  httpStatus?: number | null;
}

interface BackendAdminTokenResult {
  ok: boolean;
  message: string;
  token?: string;
  envPath?: string;
}

export function resolveBackendMcpConfigPath(
  settings: Pick<
    LifeAssistantSettings,
    "backendMcpConfigPath" | "backendEnvPath" | "backendPath"
  >,
): BackendMcpPathResolution {
  const envResolution = resolveBackendEnvPath(settings);
  const overridePath = settings.backendMcpConfigPath?.trim();
  if (overridePath) {
    const configPath = resolve(overridePath);
    const examplePath =
      envResolution.ok && envResolution.envPath
        ? join(
            dirname(envResolution.envPath),
            "server",
            "data",
            "mcp_servers.example.json",
          )
        : join(dirname(configPath), "mcp_servers.example.json");
    return {
      ok: true,
      configPath,
      examplePath,
      derivedFromBackendEnvPath: false,
      message: "",
    };
  }

  if (!envResolution.ok || !envResolution.envPath) {
    return {
      ok: false,
      derivedFromBackendEnvPath: false,
      message: "请先配置“后端 .env 路径”，再编辑 MCP 配置文件。",
    };
  }

  const projectRoot = dirname(envResolution.envPath);
  return {
    ok: true,
    configPath: join(projectRoot, "server", "data", "mcp_servers.json"),
    examplePath: join(projectRoot, "server", "data", "mcp_servers.example.json"),
    derivedFromBackendEnvPath: true,
    message: "当前路径由“后端 .env 路径”自动推导。",
  };
}

export function validateMcpConfigText(text: string): McpConfigValidationResult {
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return {
      ok: false,
      message: `JSON 格式无效：${message}`,
      serverNames: [],
    };
  }

  if (!isPlainObject(parsed)) {
    return {
      ok: false,
      message: "MCP 配置必须是一个 JSON 对象。",
      serverNames: [],
    };
  }

  const rawServers = parsed.mcpServers;
  if (!isPlainObject(rawServers)) {
    return {
      ok: false,
      message: "`mcpServers` 必须是一个对象。",
      serverNames: [],
    };
  }

  const serverNames = Object.keys(rawServers);
  for (const serverName of serverNames) {
    const rawDefinition = rawServers[serverName];
    if (!isPlainObject(rawDefinition)) {
      return {
        ok: false,
        message: `MCP 服务“${serverName}”必须是一个对象。`,
        serverNames: [],
      };
    }

    const transport =
      typeof rawDefinition.transport === "string" && rawDefinition.transport.trim()
        ? rawDefinition.transport.trim()
        : "stdio";

    if (transport !== "stdio" && transport !== "sse") {
      return {
        ok: false,
        message: `MCP 服务“${serverName}”使用了不支持的 transport：“${transport}”。`,
        serverNames: [],
      };
    }

    if (
      transport === "stdio" &&
      (typeof rawDefinition.command !== "string" || !rawDefinition.command.trim())
    ) {
      return {
        ok: false,
        message: `MCP 服务“${serverName}”需要填写非空的 "command"。`,
        serverNames: [],
      };
    }

    if (
      transport === "sse" &&
      (typeof rawDefinition.url !== "string" || !rawDefinition.url.trim())
    ) {
      return {
        ok: false,
        message: `MCP 服务“${serverName}”需要填写非空的 "url"。`,
        serverNames: [],
      };
    }

    if (
      rawDefinition.args !== undefined &&
      (!Array.isArray(rawDefinition.args) ||
        rawDefinition.args.some((item) => typeof item !== "string"))
    ) {
      return {
        ok: false,
        message: `MCP 服务“${serverName}”的 "args" 数组格式不正确。`,
        serverNames: [],
      };
    }

    if (
      rawDefinition.env !== undefined &&
      !isPlainObject(rawDefinition.env)
    ) {
      return {
        ok: false,
        message: `MCP 服务“${serverName}”的 "env" 对象格式不正确。`,
        serverNames: [],
      };
    }
  }

  return {
    ok: true,
    message:
      serverNames.length > 0
        ? `配置有效，当前共定义 ${serverNames.length} 个 MCP 服务：${serverNames.join("、")}。`
        : "配置有效，但当前还没有定义任何 MCP 服务。",
    serverNames,
  };
}

export function loadMcpConfigLocally(
  settings: Pick<
    LifeAssistantSettings,
    "backendMcpConfigPath" | "backendEnvPath" | "backendPath"
  >,
): LocalMcpConfigResult {
  const resolution = resolveBackendMcpConfigPath(settings);
  if (!resolution.ok || !resolution.configPath) {
    return {
      ok: false,
      message: resolution.message,
      exists: false,
    };
  }

  if (!existsSync(resolution.configPath)) {
    return {
      ok: true,
      configPath: resolution.configPath,
      examplePath: resolution.examplePath,
      text: "",
      exists: false,
      message: `MCP 配置文件尚不存在：${resolution.configPath}`,
    };
  }

  try {
    return {
      ok: true,
      configPath: resolution.configPath,
      examplePath: resolution.examplePath,
      text: readFileSync(resolution.configPath, "utf8"),
      exists: true,
      message: `已从 ${resolution.configPath} 载入 MCP 配置。`,
    };
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return {
      ok: false,
      configPath: resolution.configPath,
      examplePath: resolution.examplePath,
      exists: true,
      message: `读取 MCP 配置失败：${message}`,
    };
  }
}

export function createMcpConfigFromExample(
  settings: Pick<
    LifeAssistantSettings,
    "backendMcpConfigPath" | "backendEnvPath" | "backendPath"
  >,
): LocalMcpConfigResult {
  const resolution = resolveBackendMcpConfigPath(settings);
  if (!resolution.ok || !resolution.configPath || !resolution.examplePath) {
    return {
      ok: false,
      message: resolution.message,
    };
  }

  if (!existsSync(resolution.examplePath)) {
    return {
      ok: false,
      configPath: resolution.configPath,
      examplePath: resolution.examplePath,
      message: `缺少 MCP 示例配置文件：${resolution.examplePath}`,
    };
  }

  if (existsSync(resolution.configPath)) {
    return {
      ok: false,
      configPath: resolution.configPath,
      examplePath: resolution.examplePath,
      message: `MCP 配置文件已存在：${resolution.configPath}`,
    };
  }

  try {
    mkdirSync(dirname(resolution.configPath), { recursive: true });
    copyFileSync(resolution.examplePath, resolution.configPath);

    return {
      ok: true,
      configPath: resolution.configPath,
      examplePath: resolution.examplePath,
      text: readFileSync(resolution.configPath, "utf8"),
      exists: true,
      message: `已根据示例文件创建 MCP 配置：${resolution.configPath}`,
    };
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return {
      ok: false,
      configPath: resolution.configPath,
      examplePath: resolution.examplePath,
      message: `创建 MCP 配置失败：${message}`,
    };
  }
}

export function saveMcpConfigLocally(
  settings: Pick<
    LifeAssistantSettings,
    "backendMcpConfigPath" | "backendEnvPath" | "backendPath"
  >,
  text: string,
): LocalMcpConfigResult {
  const resolution = resolveBackendMcpConfigPath(settings);
  if (!resolution.ok || !resolution.configPath) {
    return {
      ok: false,
      message: resolution.message,
    };
  }

  const validation = validateMcpConfigText(text);
  if (!validation.ok) {
    return {
      ok: false,
      configPath: resolution.configPath,
      examplePath: resolution.examplePath,
      text,
      message: validation.message,
    };
  }

  try {
    mkdirSync(dirname(resolution.configPath), { recursive: true });
    writeFileSync(resolution.configPath, text, "utf8");

    return {
      ok: true,
      configPath: resolution.configPath,
      examplePath: resolution.examplePath,
      text,
      exists: true,
      message: `已将 MCP 配置保存到 ${resolution.configPath}。`,
    };
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return {
      ok: false,
      configPath: resolution.configPath,
      examplePath: resolution.examplePath,
      text,
      message: `保存 MCP 配置失败：${message}`,
    };
  }
}

export async function reloadMcpConfigLocally(
  settings: Pick<
    LifeAssistantSettings,
    "backendEnvPath" | "backendPath" | "backendMcpConfigPath"
  >,
  client: Pick<AgentClient, "reloadConfig">,
): Promise<LocalMcpConfigResult> {
  const tokenResult = resolveBackendAdminToken(settings);
  if (!tokenResult.ok || !tokenResult.token) {
    return {
      ok: false,
      message: tokenResult.message,
    };
  }

  const reloadResult = await client.reloadConfig(tokenResult.token);
  return mapReloadResult(reloadResult);
}

export async function fetchMcpRuntimeStatus(
  settings: Pick<
    LifeAssistantSettings,
    "backendEnvPath" | "backendPath" | "backendMcpConfigPath"
  >,
  client: Pick<AgentClient, "getMcpStatus">,
): Promise<McpRuntimeStatusResult> {
  const tokenResult = resolveBackendAdminToken(settings);
  if (!tokenResult.ok || !tokenResult.token) {
    return {
      ok: false,
      httpStatus: null,
      message: tokenResult.message,
    };
  }

  const result = await client.getMcpStatus(tokenResult.token);
  if (!result.ok || !result.data) {
    return {
      ok: false,
      httpStatus: result.status,
      message: formatAdminRequestFailure(result, "获取 MCP 运行状态"),
    };
  }

  return {
    ok: true,
    status: result.data,
    httpStatus: result.status,
    message:
      result.data.connected_servers.length > 0
        ? `当前已连接的 MCP 服务：${result.data.connected_servers.join("、")}`
        : "当前没有已连接的 MCP 服务。",
  };
}

export function formatMcpRuntimeStatus(status: MCPRuntimeStatus): string {
  const lines = [
    `配置文件：${status.config_path}`,
    `示例文件：${status.example_config_path}`,
    `配置是否存在：${status.config_exists ? "是" : "否"}`,
    `已连接服务：${status.connected_servers.length > 0 ? status.connected_servers.join("、") : "无"}`,
  ];

  const toolEntries = Object.entries(status.tools_by_server);
  if (toolEntries.length === 0) {
    lines.push("服务工具详情：无");
  } else {
    lines.push("服务工具详情：");
    for (const [serverName, toolNames] of toolEntries) {
      lines.push(`- ${serverName}：${toolNames.join("、")}`);
    }
  }

  lines.push(
    `最近一次重载：${
      status.last_reload_ok === undefined || status.last_reload_ok === null
        ? "尚未执行"
        : status.last_reload_ok
          ? "成功"
          : "失败"
    }`,
  );

  if (status.last_reload_at) {
    lines.push(`重载时间：${status.last_reload_at}`);
  }
  if (status.last_reload_error) {
    lines.push(`错误信息：${status.last_reload_error}`);
  }

  return lines.join("\n");
}

function resolveBackendAdminToken(
  settings: Pick<
    LifeAssistantSettings,
    "backendEnvPath" | "backendPath" | "backendMcpConfigPath"
  >,
): BackendAdminTokenResult {
  const envResolution = resolveBackendEnvPath(settings);
  if (!envResolution.ok || !envResolution.envPath) {
    return {
      ok: false,
      message: "请先配置“后端 .env 路径”，再查看 MCP 运行状态或执行重载。",
    };
  }

  const adminEnabled = readEnvValue(envResolution.envPath, ADMIN_ENABLED_KEY);
  if (!isTruthyEnvValue(adminEnabled)) {
    return {
      ok: false,
      envPath: envResolution.envPath,
      message:
        `${envResolution.envPath} 中未开启后端热重载。` +
        `请设置 ${ADMIN_ENABLED_KEY}=true 后再查看 MCP 状态或执行重载。`,
    };
  }

  const token = readEnvValue(envResolution.envPath, ADMIN_TOKEN_KEY)?.trim();
  if (!token) {
    return {
      ok: false,
      envPath: envResolution.envPath,
      message:
        `${envResolution.envPath} 中缺少 ${ADMIN_TOKEN_KEY}。` +
        "因此无法查询 MCP 状态或执行后端重载。",
    };
  }

  return {
    ok: true,
    token,
    envPath: envResolution.envPath,
    message: "",
  };
}

function mapReloadResult(result: ReloadConfigResult): LocalMcpConfigResult {
  if (result.ok) {
    return {
      ok: true,
      reloadStatus: result.status,
      message: "已保存 MCP 配置，并完成后端热重载。",
    };
  }

  return {
    ok: false,
    reloadStatus: result.status,
    message: formatAdminRequestFailure(result, "后端重载"),
  };
}

function formatAdminRequestFailure(
  result: {
    status: number | null;
    detail?: string | null;
  },
  action: string,
): string {
  if (result.status === null) {
    return `${action}失败：当前后端不可访问。`;
  }
  if (result.detail) {
    return `${action}失败（HTTP ${result.status}）：${result.detail}`;
  }
  return `${action}失败（HTTP ${result.status}）。`;
}

function formatReloadFailure(result: {
  status: number | null;
  detail?: string | null;
}): string {
  return formatAdminRequestFailure(result, "后端重载");
}

function isPlainObject(value: unknown): value is Record<string, any> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}
