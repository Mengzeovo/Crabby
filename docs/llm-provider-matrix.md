# LLM Provider Preset Matrix

Last checked: 2026-05-11.

This project keeps first-party `anthropic`, `openai`, and `ollama` support, then adds a small set of domestic OpenAI-compatible presets. Providers not listed here should use `custom_openai` with an explicit base URL and API key.

| Provider ID | API surface | Default base URL | API key env fallback | Built-in model examples | Enabled request extensions |
| --- | --- | --- | --- | --- | --- |
| `deepseek` | OpenAI-compatible chat completions | `https://api.deepseek.com` | `DEEPSEEK_API_KEY` | `deepseek-v4-flash`, `deepseek-v4-pro` | `thinking`, `reasoning_effort` |
| `qwen` | DashScope Coding Plan OpenAI-compatible chat completions | `https://coding.dashscope.aliyuncs.com/v1` | `BAILIAN_CODING_PLAN_API_KEY`, falling back to `DASHSCOPE_API_KEY` | `qwen3.6-plus`, `qwen3.5-plus`, `qwen3-max-2026-01-23`, `qwen3-coder-next`, `qwen3-coder-plus`, `glm-5`, `glm-4.7`, `kimi-k2.5`, `MiniMax-M2.5` | `enable_thinking`, `preserve_thinking`; streams `reasoning_content`; streaming tool calls disabled |
| `kimi` | Kimi Code OpenAI-compatible chat completions | `https://api.kimi.com/coding/v1` | `KIMI_API_KEY` | `kimi-for-coding` | `thinking`; streams `reasoning_content` |
| `minimax` | MiniMax OpenAI-compatible text API | `https://api.minimax.io/v1` | `MINIMAX_API_KEY` | `MiniMax-M2.7`, `MiniMax-M2.7-highspeed`, `MiniMax-M2.5` | `reasoning_split` |
| `zhipu` | BigModel OpenAI-compatible chat completions | `https://open.bigmodel.cn/api/paas/v4` | `ZAI_API_KEY` | `glm-5.1`, `glm-5-turbo`, `glm-4.7`, `glm-4.7-flash` | `thinking` |

## Compatibility Rules

- The backend always prefers generic `LLM_API_KEY` and `LLM_BASE_URL` when present, then falls back to provider-specific legacy keys.
- Presets are deliberately conservative: unsupported request fields are not forwarded just because an API is OpenAI-compatible.
- The `qwen` UI preset is Coding Plan only. Use `https://coding.dashscope.aliyuncs.com/v1` for the China endpoint, or override the profile base URL to `https://coding-intl.dashscope.aliyuncs.com/v1` for the international endpoint. Ordinary DashScope pay-as-you-go model access is not exposed through this built-in provider.
- The `kimi` UI preset targets Kimi Code only. Use `https://api.kimi.com/coding/v1` with `kimi-for-coding`; ordinary Kimi Platform / Moonshot access is a separate product and is not exposed through this built-in provider.
- Coding Plan model capabilities are model-specific: `qwen3-coder-next` and `qwen3-coder-plus` are text-generation only, so the UI and backend do not send thinking controls for those models.
- Qwen thinking mode uses top-level OpenAI-compatible request extension fields `enable_thinking` and `preserve_thinking`, not the generic `thinking` object used by some other providers. Its reasoning stream is read from `reasoning_content`.
- Provider `usage` is displayed as provider-reported token usage, not as a priced currency charge. Usage parsing is selected by provider preset: Anthropic uses its native `input_tokens` / `output_tokens` / cache fields, OpenAI-compatible providers use OpenAI-style usage fields, and DeepSeek additionally normalizes `prompt_cache_hit_tokens`, `prompt_cache_miss_tokens`, and `completion_tokens_details.reasoning_tokens`.
- `custom_openai` exposes base URL, API key, thinking, reasoning effort, and reasoning split for manual provider experiments.
- Native provider tools such as web search, code interpreter, files, audio, video, and image generation are intentionally out of scope for the first preset pass.

## Official References

- DeepSeek: https://api-docs.deepseek.com/
- Qwen / DashScope: https://www.alibabacloud.com/help/en/model-studio/compatibility-of-openai-with-dashscope
- Qwen Coding Plan / Qwen Code: https://github.com/QwenLM/qwen-code
- Qwen3.6 API usage: https://qwen.ai/blog?id=qwen3.6
- Kimi Code API overview: https://www.kimi.com/code/docs/en/
- Kimi Code environment variables: https://www.kimi.com/code/docs/en/kimi-code-cli/configuration/environment-variables.html
- MiniMax: https://platform.minimax.io/docs/api-reference/text-openai-api
- Zhipu / BigModel: https://docs.bigmodel.cn/cn/guide/develop/openai/introduction
