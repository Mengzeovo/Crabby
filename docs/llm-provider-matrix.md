# LLM Provider Preset Matrix

Last updated: 2026-05-12

Crabby keeps first-party support for Anthropic, OpenAI, and Ollama, then adds a conservative set of OpenAI-compatible provider presets. Providers not listed here should use `custom_openai` with an explicit base URL and API key.

Profiles are backend-owned. The Obsidian plugin edits profiles through authenticated admin APIs, and the backend persists them into `.env` using `PROFILE_<id>_*` keys plus `ACTIVE_PROFILE_ID`.

## Built-In Provider IDs

| Provider ID | API surface | Default base URL | API key env fallback | Example models | Request extensions |
| --- | --- | --- | --- | --- | --- |
| `anthropic` | Anthropic Messages API | Provider default | `ANTHROPIC_API_KEY` | User-configured Claude models | Native thinking/reasoning when configured |
| `openai` | OpenAI chat completions | Provider default | `OPENAI_API_KEY` | User-configured OpenAI models | Reasoning effort when configured |
| `ollama` | OpenAI-compatible local chat | User/local configured | none by default | Local Ollama models | Conservative OpenAI-compatible fields |
| `deepseek` | OpenAI-compatible chat completions | `https://api.deepseek.com` | `DEEPSEEK_API_KEY` | `deepseek-v4-flash`, `deepseek-v4-pro` | `thinking`, `reasoning_effort` |
| `qwen` | DashScope Coding Plan OpenAI-compatible chat completions | `https://coding.dashscope.aliyuncs.com/v1` | `BAILIAN_CODING_PLAN_API_KEY`, then `DASHSCOPE_API_KEY` | `qwen3.6-plus`, `qwen3.5-plus`, `qwen3-max-2026-01-23`, `qwen3-coder-next`, `qwen3-coder-plus`, `glm-5`, `glm-4.7`, `kimi-k2.5`, `MiniMax-M2.5` | `enable_thinking`, `preserve_thinking`; streaming tool calls disabled |
| `kimi` | Kimi Code OpenAI-compatible chat completions | `https://api.kimi.com/coding/v1` | `KIMI_API_KEY` | `kimi-for-coding` | `thinking` |
| `minimax` | MiniMax OpenAI-compatible text API | `https://api.minimax.io/v1` | `MINIMAX_API_KEY` | `MiniMax-M2.7`, `MiniMax-M2.7-highspeed`, `MiniMax-M2.5` | `reasoning_split` |
| `zhipu` | BigModel OpenAI-compatible chat completions | `https://open.bigmodel.cn/api/paas/v4` | `ZAI_API_KEY` | `glm-5.1`, `glm-5-turbo`, `glm-4.7`, `glm-4.7-flash` | `thinking` |
| `custom_openai` | OpenAI-compatible chat completions | User-configured | `LLM_API_KEY` or profile key | User-configured | thinking, reasoning effort, reasoning split |

## Profile Fields

The UI and backend profile store support:

- provider ID
- model ID
- API key
- base URL
- vision support
- thinking mode
- thinking budget tokens
- reasoning effort
- reasoning split

When a profile is activated, the backend writes the effective active runtime values, including generic `LLM_API_KEY` / `LLM_BASE_URL` and provider-specific fallback values when applicable.

## Compatibility Rules

- Generic `LLM_API_KEY` and `LLM_BASE_URL` take priority when present.
- Provider-specific keys are fallback compatibility paths.
- Request fields are allowlisted by provider. Crabby does not forward arbitrary fields only because an API claims OpenAI compatibility.
- Provider usage is displayed as provider-reported token usage, not as priced currency.
- Usage normalization is selected by provider preset.
- DeepSeek additionally normalizes cache hit/miss and reasoning token fields when provided.
- Providers that do not support streaming tool calls use the backend's non-streaming tool loop in the WebSocket path.
- `custom_openai` exists for manual experiments; users should expect provider-specific rough edges.

## Reasoning Output Shapes

Crabby normalizes provider reasoning into a shared UI/history shape when available:

| Provider | Reasoning output shape |
| --- | --- |
| `anthropic` | `anthropic_blocks` |
| `deepseek` | `reasoning_content` |
| `qwen` | `reasoning_content` |
| `kimi` | `reasoning_content` |
| `minimax` | `reasoning_details` |
| `custom_openai` | `reasoning_details` |
| first-pass built-in OpenAI-compatible providers without official reasoning handling | `none` |

DeepSeek historical replay converts saved reasoning back to `reasoning_content` for thinking-mode calls.

## Provider Notes

### Qwen

The `qwen` preset targets DashScope Coding Plan, not ordinary DashScope pay-as-you-go model access.

Use the China endpoint by default:

```text
https://coding.dashscope.aliyuncs.com/v1
```

Override the profile base URL for the international endpoint:

```text
https://coding-intl.dashscope.aliyuncs.com/v1
```

Qwen thinking mode uses top-level `enable_thinking` and `preserve_thinking`, not a generic `thinking` object. Some Coding Plan models are text-generation only and should not receive thinking controls.

### Kimi

The `kimi` preset targets Kimi Code:

```text
https://api.kimi.com/coding/v1
kimi-for-coding
```

Ordinary Kimi Platform / Moonshot access is not exposed through this built-in provider. Use `custom_openai` if experimenting with a different compatible endpoint.

### MiniMax

MiniMax uses `reasoning_split` for supported models. Treat model capability as model-specific.

### Zhipu

The `zhipu` preset targets BigModel OpenAI-compatible chat completions and uses `ZAI_API_KEY` as the provider-specific fallback.

## Active Profile Test

`POST /admin/profile/test` checks the active profile and can run low-token live probes for supported providers. Use it after creating or editing a profile. It is authenticated with `X-Crabby-Admin-Token`.

## Out Of Scope For The Current Preset Pass

Provider-native tools and modalities are not automatically exposed by these presets:

- web search
- code interpreter
- file APIs
- audio/video APIs
- image generation
- provider-hosted retrieval

These should be added as explicit product features or tools, not smuggled through generic provider config.

## References

- DeepSeek: https://api-docs.deepseek.com/
- Qwen / DashScope OpenAI compatibility: https://www.alibabacloud.com/help/en/model-studio/compatibility-of-openai-with-dashscope
- Qwen Code: https://github.com/QwenLM/qwen-code
- Qwen3.6 API usage: https://qwen.ai/blog?id=qwen3.6
- Kimi Code API overview: https://www.kimi.com/code/docs/en/
- Kimi Code environment variables: https://www.kimi.com/code/docs/en/kimi-code-cli/configuration/environment-variables.html
- MiniMax: https://platform.minimax.io/docs/api-reference/text-openai-api
- Zhipu / BigModel: https://docs.bigmodel.cn/cn/guide/develop/openai/introduction
