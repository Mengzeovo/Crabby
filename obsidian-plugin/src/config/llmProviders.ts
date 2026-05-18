export const LLM_PROVIDER_IDS = [
  "anthropic",
  "openai",
  "deepseek",
  "qwen",
  "kimi",
  "minimax",
  "zhipu",
  "custom_openai",
] as const;

export type LlmProviderId = (typeof LLM_PROVIDER_IDS)[number];

export interface LlmModelPreset {
  id: string;
  label: string;
  supportsVision?: boolean;
  supportsThinking?: boolean;
}

export interface LlmProviderCapabilities {
  baseUrl: boolean;
  apiKey: boolean;
  vision: boolean;
  thinking: boolean;
  thinkingBudget: boolean;
  reasoningEffort: boolean;
  reasoningSplit: boolean;
}

export interface LlmProviderPreset {
  id: LlmProviderId;
  label: string;
  badge: string;
  defaultBaseUrl: string;
  apiKeyEnv: string;
  models: LlmModelPreset[];
  capabilities: LlmProviderCapabilities;
  reasoningEfforts?: string[];
}

const DEFAULT_CAPABILITIES: LlmProviderCapabilities = {
  baseUrl: true,
  apiKey: true,
  vision: false,
  thinking: false,
  thinkingBudget: false,
  reasoningEffort: false,
  reasoningSplit: false,
};

export const LLM_PROVIDER_PRESETS: Record<LlmProviderId, LlmProviderPreset> = {
  anthropic: {
    id: "anthropic",
    label: "Anthropic",
    badge: "#d97706",
    defaultBaseUrl: "",
    apiKeyEnv: "ANTHROPIC_API_KEY",
    models: [
      { id: "claude-sonnet-4-20250514", label: "Claude Sonnet 4" },
    ],
    capabilities: {
      ...DEFAULT_CAPABILITIES,
      baseUrl: false,
      vision: true,
      thinking: true,
      thinkingBudget: true,
    },
  },
  openai: {
    id: "openai",
    label: "OpenAI",
    badge: "#059669",
    defaultBaseUrl: "https://api.openai.com/v1",
    apiKeyEnv: "OPENAI_API_KEY",
    models: [
      { id: "gpt-5.4-mini", label: "GPT-5.4 Mini", supportsVision: true },
      { id: "gpt-5.4", label: "GPT-5.4", supportsVision: true },
    ],
    capabilities: {
      ...DEFAULT_CAPABILITIES,
      vision: true,
      reasoningEffort: true,
    },
    reasoningEfforts: ["none", "minimal", "low", "medium", "high", "xhigh"],
  },
  deepseek: {
    id: "deepseek",
    label: "DeepSeek",
    badge: "#4f46e5",
    defaultBaseUrl: "https://api.deepseek.com",
    apiKeyEnv: "DEEPSEEK_API_KEY",
    models: [
      { id: "deepseek-v4-flash", label: "DeepSeek V4 Flash" },
      { id: "deepseek-v4-pro", label: "DeepSeek V4 Pro" },
    ],
    capabilities: {
      ...DEFAULT_CAPABILITIES,
      thinking: true,
      reasoningEffort: true,
    },
    reasoningEfforts: ["high", "max"],
  },
  qwen: {
    id: "qwen",
    label: "Qwen Coding Plan",
    badge: "#0891b2",
    defaultBaseUrl: "https://coding.dashscope.aliyuncs.com/v1",
    apiKeyEnv: "BAILIAN_CODING_PLAN_API_KEY",
    models: [
      {
        id: "qwen3.6-plus",
        label: "千问 qwen3.6-plus",
        supportsVision: true,
        supportsThinking: true,
      },
      {
        id: "qwen3.5-plus",
        label: "千问 qwen3.5-plus",
        supportsVision: true,
        supportsThinking: true,
      },
      {
        id: "qwen3-max-2026-01-23",
        label: "千问 qwen3-max-2026-01-23",
        supportsVision: false,
        supportsThinking: true,
      },
      {
        id: "qwen3-coder-next",
        label: "千问 qwen3-coder-next",
        supportsVision: false,
        supportsThinking: false,
      },
      {
        id: "qwen3-coder-plus",
        label: "千问 qwen3-coder-plus",
        supportsVision: false,
        supportsThinking: false,
      },
      {
        id: "glm-5",
        label: "智谱 glm-5",
        supportsVision: false,
        supportsThinking: true,
      },
      {
        id: "glm-4.7",
        label: "智谱 glm-4.7",
        supportsVision: false,
        supportsThinking: true,
      },
      {
        id: "kimi-k2.5",
        label: "Kimi kimi-k2.5",
        supportsVision: true,
        supportsThinking: true,
      },
      {
        id: "MiniMax-M2.5",
        label: "MiniMax M2.5",
        supportsVision: false,
        supportsThinking: true,
      },
    ],
    capabilities: {
      ...DEFAULT_CAPABILITIES,
      vision: true,
      thinking: true,
    },
  },
  kimi: {
    id: "kimi",
    label: "Kimi Code",
    badge: "#7c3aed",
    defaultBaseUrl: "https://api.kimi.com/coding/v1",
    apiKeyEnv: "KIMI_API_KEY",
    models: [
      {
        id: "kimi-for-coding",
        label: "Kimi for Coding",
        supportsVision: true,
        supportsThinking: true,
      },
    ],
    capabilities: {
      ...DEFAULT_CAPABILITIES,
      vision: true,
      thinking: true,
    },
  },
  minimax: {
    id: "minimax",
    label: "MiniMax",
    badge: "#db2777",
    defaultBaseUrl: "https://api.minimax.io/v1",
    apiKeyEnv: "MINIMAX_API_KEY",
    models: [
      { id: "MiniMax-M2.7", label: "MiniMax M2.7" },
      { id: "MiniMax-M2.7-highspeed", label: "MiniMax M2.7 Highspeed" },
      { id: "MiniMax-M2.5", label: "MiniMax M2.5" },
    ],
    capabilities: {
      ...DEFAULT_CAPABILITIES,
      reasoningSplit: true,
    },
  },
  zhipu: {
    id: "zhipu",
    label: "Zhipu GLM",
    badge: "#16a34a",
    defaultBaseUrl: "https://open.bigmodel.cn/api/paas/v4",
    apiKeyEnv: "ZAI_API_KEY",
    models: [
      { id: "glm-5.1", label: "GLM-5.1" },
      { id: "glm-5-turbo", label: "GLM-5 Turbo" },
      { id: "glm-4.7", label: "GLM-4.7" },
      { id: "glm-4.7-flash", label: "GLM-4.7 Flash" },
    ],
    capabilities: {
      ...DEFAULT_CAPABILITIES,
      vision: true,
      thinking: true,
    },
  },
  custom_openai: {
    id: "custom_openai",
    label: "Custom OpenAI",
    badge: "#64748b",
    defaultBaseUrl: "https://api.openai.com/v1",
    apiKeyEnv: "LLM_API_KEY",
    models: [],
    capabilities: {
      ...DEFAULT_CAPABILITIES,
      vision: true,
      thinking: true,
      thinkingBudget: true,
      reasoningEffort: true,
      reasoningSplit: true,
    },
    reasoningEfforts: ["none", "minimal", "low", "medium", "high", "max", "xhigh"],
  },
};

export function isLlmProviderId(value: unknown): value is LlmProviderId {
  return (
    typeof value === "string" &&
    (LLM_PROVIDER_IDS as readonly string[]).includes(value)
  );
}

export function normalizeLlmProviderId(value: unknown): LlmProviderId {
  return isLlmProviderId(value) ? value : "custom_openai";
}

export function getLlmProviderPreset(provider: LlmProviderId): LlmProviderPreset {
  return LLM_PROVIDER_PRESETS[provider];
}

export function getReasoningEffortHint(provider: LlmProviderId): string {
  return getLlmProviderPreset(provider).reasoningEfforts?.join(" | ") ?? "";
}

export function getDefaultModelForProvider(provider: LlmProviderId): string {
  return getLlmProviderPreset(provider).models[0]?.id ?? "";
}

export function findModelPreset(
  provider: LlmProviderId,
  model: string,
): LlmModelPreset | undefined {
  return getLlmProviderPreset(provider).models.find((item) => item.id === model);
}
