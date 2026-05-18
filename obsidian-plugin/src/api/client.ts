/**
 * API client for the Crabby backend.
 * Supports both REST (fallback) and WebSocket (streaming).
 */

export interface UserCommand {
  name: string;
  args: string;
}

export interface VaultFileAttachment {
  type: "vault_file";
  attachment_id?: string;
  path: string;
  content?: string;
  truncated?: boolean;
  line_start?: number | null;
  line_end?: number | null;
}

export interface VaultDirectoryAttachment {
  type: "vault_directory";
  attachment_id?: string;
  path: string;
  content?: string;
  truncated?: boolean;
  entry_count?: number;
}

export interface ImageAttachment {
  type: "image";
  attachment_id?: string;
  filename: string;
  media_type: string;
  width?: number | null;
  height?: number | null;
  size_bytes?: number;
  source_path?: string | null;
  preview_url?: string;
}

export type MessageAttachment =
  | VaultFileAttachment
  | VaultDirectoryAttachment
  | ImageAttachment;

export interface ImagePaste {
  id: number;
  type: "image";
  data: string;
  media_type: string;
  filename: string;
  width?: number;
  height?: number;
  source_path?: string;
}

export interface ChatRequestPayload {
  content: string;
  pasted_contents?: ImagePaste[];
  session_id?: string | null;
  conversation_id?: string | null;
  persona_mode?: string | null;
  manual_persona_id?: string | null;
}

export type ToolCallStatus = "success" | "warning" | "error" | string;

export interface ToolCallPayload {
  id?: string | null;
  tool_use_id?: string | null;
  name?: string;
  tool?: string;
  output?: string;
  metadata?: Record<string, unknown>;
  status?: ToolCallStatus;
  is_error?: boolean;
  is_truncated?: boolean;
  cache_path?: string | null;
  elapsed_ms?: number;
}

export interface ChatResponse {
  reply: string;
  tool_calls: ToolCallPayload[];
  session_id: string;
  conversation_id: string;
  branch_fingerprint: string;
  message_id?: string | null;
  user_message_id?: string | null;
  warnings?: string[];
  context?: ContextStats;
  persona_state: PersonaState;
}

export interface ActualTokenUsage {
  call_count: number;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  reasoning_tokens: number;
  cache_creation_input_tokens: number;
  cache_read_input_tokens: number;
  prompt_cache_hit_tokens?: number;
  prompt_cache_miss_tokens?: number;
  prompt_cached_tokens?: number;
}

/** Context usage stats returned with each completed turn. */
export interface ContextStats {
  total_tokens: number;
  system_tokens: number;
  schema_tokens: number;
  user_tokens: number;
  assistant_tokens: number;
  tool_result_tokens: number;
  message_count: number;
  context_limit: number;
  usage_percent: number;
  actual_usage?: ActualTokenUsage | null;
  cumulative_usage?: ActualTokenUsage | null;
}

/** Session info returned by the backend. */
export interface SessionInfo {
  id: string;
  title: string;
  turn_count: number;
  message_count: number;
  created_at: number;
  last_activity_at: number;
  root_conversation_id: string;
  active_conversation_id: string;
  branch_fingerprint: string;
  persona_state: PersonaState;
}

/** A conversation branch inside a backend session. */
export interface ConversationInfo {
  id: string;
  session_id: string;
  parent_id?: string | null;
  fork_message_id?: string | null;
  revision: number;
  created_at: number;
  last_activity_at: number;
  title: string;
  message_count: number;
  file: string;
  active: boolean;
  branch_fingerprint: string;
}

/** A single message in a session's history. */
export interface SessionMessage {
  role: string;
  message_id?: string | null;
  content?: unknown;
  text?: string;
  model_text?: string;
  command?: UserCommand;
  attachments?: MessageAttachment[];
}

export interface SkillSummary {
  name: string;
  description: string;
  aliases?: string[];
}

export interface PersonaSummary {
  id: string;
  title: string;
  description: string;
}

export interface PersonaState {
  mode: "auto" | "none" | "manual";
  manual_persona_id: string | null;
  active_persona_id: string | null;
  source: string;
  status: string;
}

export interface PatchSessionPayload {
  title?: string;
  active_conversation_id?: string | null;
  persona_mode?: string | null;
  manual_persona_id?: string | null;
}

export interface BackendCapabilities {
  supports_vision: boolean;
}

/** Error payload sent when a streaming error occurs. */
export interface StreamErrorPayload {
  message: string;
  code: string;
}

/** Events emitted during a streaming chat turn. */
export interface StreamCallbacks {
  onAssistantPrefix?: (text: string) => void;
  onReasoningDelta?: (text: string) => void;
  onTextDelta?: (text: string) => void;
  onToolStart?: (name: string, id: string) => void;
  onToolResult?: (payload: ToolCallPayload) => void;
  onDone?: (
    sessionId: string,
    conversationId: string,
    assistantMessageId?: string | null,
    userMessageId?: string | null,
    context?: ContextStats,
    personaState?: PersonaState,
  ) => void;
  onError?: (payload: StreamErrorPayload) => void;
  onWarning?: (message: string) => void;
}

export interface SystemNotificationEvent {
  message: string;
  autoTrigger: boolean;
}

export interface ReloadConfigResult {
  ok: boolean;
  status: number | null;
  detail?: string | null;
}

export interface MCPRuntimeStatus {
  config_path: string;
  example_config_path: string;
  config_exists: boolean;
  connected_servers: string[];
  tools_by_server: Record<string, string[]>;
  last_reload_ok?: boolean | null;
  last_reload_error?: string | null;
  last_reload_at?: string | null;
  vault_tools_enabled?: boolean;
  vault_tools_tools?: string[];
}

export interface MCPStatusResult {
  ok: boolean;
  status: number | null;
  detail?: string | null;
  data?: MCPRuntimeStatus;
}

export interface ProfileTestResponse {
  ok: boolean;
  provider: string;
  model: string;
  base_url: string | null;
  api_key_configured: boolean;
  live_probe: boolean;
  reasoning_output_shape: string;
  reasoning_detected: boolean | null;
  reasoning_field: string | null;
  message: string;
}

export interface ProfileTestResult {
  ok: boolean;
  status: number | null;
  detail?: string | null;
  data?: ProfileTestResponse;
}

export interface BackendLlmProfile {
  id: string;
  name: string;
  provider: string;
  model: string;
  baseUrl: string;
  apiKey: string;
  supportsVision: boolean;
  thinkingMode: string;
  thinkingEffort: string;
  thinkingBudgetTokens: string;
  reasoningSplit: boolean;
}

export interface BackendLlmProfilesResponse {
  envPath: string;
  profiles: BackendLlmProfile[];
  activeProfileId: string;
}

export interface BackendLlmProfilesResult {
  ok: boolean;
  status: number | null;
  detail?: string | null;
  data?: BackendLlmProfilesResponse;
}

const WEB_SOCKET_CONNECTION_FAILED_MESSAGE =
  "WebSocket connection failed. Please confirm the backend is running.";
const WEB_SOCKET_STREAM_INTERRUPTED_MESSAGE =
  "WebSocket connection lost while streaming. Please retry.";

export class WebSocketTransportError extends Error {
  readonly canFallbackToRest: boolean;

  constructor(message: string, canFallbackToRest: boolean) {
    super(message);
    Object.setPrototypeOf(this, new.target.prototype);
    this.name = "WebSocketTransportError";
    this.canFallbackToRest = canFallbackToRest;
  }
}

export class WebSocketServerError extends Error {
  constructor(message: string) {
    super(message);
    Object.setPrototypeOf(this, new.target.prototype);
    this.name = "WebSocketServerError";
  }
}

export function shouldFallbackToRest(error: unknown): boolean {
  return error instanceof WebSocketTransportError && error.canFallbackToRest;
}

export function createDefaultPersonaState(): PersonaState {
  return {
    mode: "auto",
    manual_persona_id: null,
    active_persona_id: null,
    source: "none",
    status: "unresolved",
  };
}

export class AgentClient {
  private ws: WebSocket | null = null;
  private pendingCallbacks: StreamCallbacks | null = null;
  private pendingUserOnError: ((payload: StreamErrorPayload) => void) | null = null;
  private pendingResolve: (() => void) | null = null;
  private pendingReject: ((error: Error) => void) | null = null;
  private pendingMessageSent = false;
  private _sessionId: string | null = null;
  private _conversationId: string | null = null;
  private _wsHandlers: {
    onopen: () => void;
    onerror: () => void;
    onmessage: (evt: MessageEvent) => void;
    onclose: () => void;
  } | null = null;

  /** Global listener for out-of-band system notifications (e.g. background task completion). */
  public onSysNotify?: (event: SystemNotificationEvent) => void;

  constructor(private baseUrl: string = "http://127.0.0.1:8000") {}

  get sessionId(): string | null {
    return this._sessionId;
  }

  get conversationId(): string | null {
    return this._conversationId;
  }

  setBaseUrl(baseUrl: string): void {
    const normalized = baseUrl.trim();
    if (!normalized || normalized === this.baseUrl) {
      return;
    }
    if (this.ws) {
      if (this._wsHandlers) {
        this.ws.removeEventListener("open", this._wsHandlers.onopen);
        this.ws.removeEventListener("error", this._wsHandlers.onerror);
        this.ws.removeEventListener("message", this._wsHandlers.onmessage);
        this.ws.removeEventListener("close", this._wsHandlers.onclose);
        this._wsHandlers = null;
      }
      this.ws.close();
      this.ws = null;
    }
    this.baseUrl = normalized;
  }

  getAttachmentUrl(attachmentId: string): string {
    return `${this.baseUrl}/attachments/${attachmentId}`;
  }

  /** Switch to a session/conversation pair. Drops the current WebSocket. */
  setSession(sessionId: null): void;
  setSession(sessionId: string, conversationId: string): void;
  setSession(sessionId: string | null, conversationId: string | null = null): void {
    if (sessionId && !conversationId) {
      throw new Error("conversationId is required when sessionId is set");
    }
    if (this.ws) {
      if (this._wsHandlers) {
        this.ws.removeEventListener("open", this._wsHandlers.onopen);
        this.ws.removeEventListener("error", this._wsHandlers.onerror);
        this.ws.removeEventListener("message", this._wsHandlers.onmessage);
        this.ws.removeEventListener("close", this._wsHandlers.onclose);
        this._wsHandlers = null;
      }
      this.ws.close();
      this.ws = null;
    }
    this._sessionId = sessionId;
    this._conversationId = sessionId ? conversationId : null;
  }

  private resetPendingStream(): void {
    this.pendingCallbacks = null;
    this.pendingUserOnError = null;
    this.pendingResolve = null;
    this.pendingReject = null;
    this.pendingMessageSent = false;
  }

  private resolvePendingStream(): void {
    const resolve = this.pendingResolve;
    this.resetPendingStream();
    resolve?.();
  }

  private rejectPendingStream(error: Error): void {
    const reject = this.pendingReject;
    this.resetPendingStream();
    reject?.(error);
  }

  private failPendingStreamFromSocket(
    message: string,
    canFallbackToRest: boolean,
    notifyUser: boolean,
  ): void {
    const onError = this.pendingUserOnError;
    const reject = this.pendingReject;
    if (!reject) {
      return;
    }

    this.resetPendingStream();
    reject(new WebSocketTransportError(message, canFallbackToRest));
    if (notifyUser) {
      onError?.({ message, code: "TRANSPORT_ERROR" });
    }
  }

  async listSessions(): Promise<SessionInfo[]> {
    const resp = await fetch(`${this.baseUrl}/sessions`);
    if (!resp.ok) throw new Error(`Sessions API error: ${resp.status}`);
    return (await resp.json()) as SessionInfo[];
  }

  async createSession(sessionId?: string): Promise<SessionInfo> {
    const init: RequestInit = { method: "POST" };
    if (sessionId) {
      init.headers = { "Content-Type": "application/json" };
      init.body = JSON.stringify({ session_id: sessionId });
    }

    const resp = await fetch(`${this.baseUrl}/sessions`, init);
    if (!resp.ok) {
      const detail = await readErrorDetail(resp);
      throw new Error(detail || `Create session API error: ${resp.status}`);
    }
    const session = (await resp.json()) as SessionInfo;
    this.applySessionInfo(session);
    return session;
  }

  async getSession(sessionId: string): Promise<SessionInfo> {
    const resp = await fetch(
      `${this.baseUrl}/sessions/${encodeURIComponent(sessionId)}`,
    );
    if (!resp.ok) {
      const detail = await readErrorDetail(resp);
      throw new Error(detail || `Session API error: ${resp.status}`);
    }
    return (await resp.json()) as SessionInfo;
  }

  async listConversations(sessionId: string): Promise<ConversationInfo[]> {
    const resp = await fetch(
      `${this.baseUrl}/sessions/${encodeURIComponent(sessionId)}/conversations`,
    );
    if (!resp.ok) throw new Error(`Conversations API error: ${resp.status}`);
    return (await resp.json()) as ConversationInfo[];
  }

  async getConversationMessages(
    sessionId: string,
    conversationId: string,
  ): Promise<SessionMessage[]> {
    const resp = await fetch(
      `${this.baseUrl}/sessions/${encodeURIComponent(sessionId)}/conversations/${encodeURIComponent(conversationId)}/messages`,
    );
    if (!resp.ok) {
      throw new Error(`Conversation messages API error: ${resp.status}`);
    }
    return (await resp.json()) as SessionMessage[];
  }

  async forkConversation(
    sessionId: string,
    parentConversationId: string,
    forkMessageId: string,
    title?: string,
  ): Promise<SessionInfo> {
    const resp = await fetch(
      `${this.baseUrl}/sessions/${encodeURIComponent(sessionId)}/conversations/${encodeURIComponent(parentConversationId)}/fork`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          fork_message_id: forkMessageId,
          title: title ?? "",
        }),
      },
    );
    if (!resp.ok) {
      const detail = await readErrorDetail(resp);
      throw new Error(detail || `Fork conversation API error: ${resp.status}`);
    }
    const session = (await resp.json()) as SessionInfo;
    if (this._sessionId === session.id || this._sessionId === null) {
      this.applySessionInfo(session);
    }
    return session;
  }

  async getConversationContextStats(
    sessionId: string,
    conversationId: string,
  ): Promise<ContextStats> {
    const resp = await fetch(
      `${this.baseUrl}/sessions/${encodeURIComponent(sessionId)}/conversations/${encodeURIComponent(conversationId)}/context-stats`,
    );
    if (!resp.ok) throw new Error(`Context stats API error: ${resp.status}`);
    const data = (await resp.json()) as Partial<ContextStats>;
    if (
      typeof data.total_tokens !== "number" ||
      typeof data.context_limit !== "number" ||
      typeof data.usage_percent !== "number"
    ) {
      throw new Error("Context stats API returned an invalid payload");
    }
    return data as ContextStats;
  }

  async listPersonas(): Promise<PersonaSummary[]> {
    const resp = await fetch(`${this.baseUrl}/personas`);
    if (!resp.ok) throw new Error(`Personas API error: ${resp.status}`);
    return (await resp.json()) as PersonaSummary[];
  }

  async listSkills(): Promise<SkillSummary[]> {
    const resp = await fetch(`${this.baseUrl}/skills`);
    if (!resp.ok) throw new Error(`Skills API error: ${resp.status}`);
    return (await resp.json()) as SkillSummary[];
  }

  async getCapabilities(): Promise<BackendCapabilities> {
    const resp = await fetch(`${this.baseUrl}/capabilities`);
    if (!resp.ok) throw new Error(`Capabilities API error: ${resp.status}`);
    return (await resp.json()) as BackendCapabilities;
  }

  async deleteSession(sessionId: string): Promise<void> {
    const resp = await fetch(
      `${this.baseUrl}/sessions/${encodeURIComponent(sessionId)}`,
      { method: "DELETE" },
    );
    if (!resp.ok && resp.status !== 204) {
      throw new Error(`Delete session API error: ${resp.status}`);
    }
    if (this._sessionId === sessionId) {
      this.setSession(null);
    }
  }

  async patchSession(
    sessionId: string,
    payload: PatchSessionPayload,
  ): Promise<SessionInfo> {
    const resp = await fetch(`${this.baseUrl}/sessions/${encodeURIComponent(sessionId)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!resp.ok) {
      const detail = await readErrorDetail(resp);
      throw new Error(detail || `Patch session API error: ${resp.status}`);
    }
    const session = (await resp.json()) as SessionInfo;
    if (this._sessionId === session.id || this._sessionId === null) {
      this.applySessionInfo(session);
    }
    return session;
  }

  async chat(
    payload: string | ChatRequestPayload,
    conversationId?: string,
  ): Promise<ChatResponse> {
    const session = await this.ensureSession();
    const request = this.normalizePayload(
      payload,
      session.id,
      conversationId ?? session.active_conversation_id,
    );
    const resp = await fetch(`${this.baseUrl}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    });

    if (!resp.ok) {
      const detail = await readErrorDetail(resp);
      throw new Error(
        detail || `Agent API error: ${resp.status} ${resp.statusText}`,
      );
    }

    const data = (await resp.json()) as ChatResponse;
    this.applyChatResponse(data);
    return data;
  }

  async streamChat(
    payload: string | ChatRequestPayload,
    callbacks: StreamCallbacks,
  ): Promise<void> {
    await this.ensureWebSocket();

    return new Promise<void>((resolve, reject) => {
      this.pendingResolve = resolve;
      this.pendingReject = reject;
      this.pendingMessageSent = false;
      this.pendingUserOnError = callbacks.onError ?? null;
      this.pendingCallbacks = {
        onAssistantPrefix: callbacks.onAssistantPrefix,
        onReasoningDelta: callbacks.onReasoningDelta,
        onTextDelta: callbacks.onTextDelta,
        onToolStart: callbacks.onToolStart,
        onToolResult: callbacks.onToolResult,
        onWarning: callbacks.onWarning,
        onDone: (
          sessionId: string,
          convId: string,
          assistantMessageId?: string | null,
          userMessageId?: string | null,
          context?: ContextStats,
          personaState?: PersonaState,
        ) => {
          this._sessionId = sessionId;
          this._conversationId = convId;
          this.resolvePendingStream();
          callbacks.onDone?.(
            sessionId,
            convId,
            assistantMessageId,
            userMessageId,
            context,
            personaState,
          );
        },
        onError: (payload: StreamErrorPayload) => {
          this.rejectPendingStream(new WebSocketServerError(payload.message));
          callbacks.onError?.(payload);
        },
      };

      try {
        const ws = this.ws;
        if (!ws) {
          throw new WebSocketTransportError(WEB_SOCKET_CONNECTION_FAILED_MESSAGE, true);
        }
        ws.send(JSON.stringify(this.normalizeWebSocketPayload(payload)));
        this.pendingMessageSent = true;
      } catch (error) {
        this.resetPendingStream();
        if (error instanceof WebSocketTransportError) {
          reject(error);
          return;
        }
        const message =
          error instanceof Error && error.message
            ? error.message
            : WEB_SOCKET_CONNECTION_FAILED_MESSAGE;
        reject(new WebSocketTransportError(message, true));
      }
    });
  }

  private async ensureWebSocket(): Promise<void> {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      return;
    }

    try {
      await this.ensureSession();
    } catch (error) {
      const message =
        error instanceof Error && error.message
          ? error.message
          : WEB_SOCKET_CONNECTION_FAILED_MESSAGE;
      throw new WebSocketTransportError(message, true);
    }

    if (!this._sessionId || !this._conversationId) {
      throw new WebSocketTransportError(WEB_SOCKET_CONNECTION_FAILED_MESSAGE, true);
    }

    const wsUrl = this.baseUrl.replace(/^http/, "ws");
    this.ws = new WebSocket(
      `${wsUrl}/sessions/${encodeURIComponent(this._sessionId)}/conversations/${encodeURIComponent(this._conversationId)}/ws`,
    );

    let opened = false;
    let settled = false;
    let resolveConnection: (() => void) | null = null;
    let rejectConnection: ((error: Error) => void) | null = null;

    const onOpen = () => {
      opened = true;
      if (settled) return;
      settled = true;
      resolveConnection?.();
    };

    const onError = () => {
      if (!opened) {
        if (settled) return;
        settled = true;
        this.ws = null;
        rejectConnection?.(new WebSocketTransportError(WEB_SOCKET_CONNECTION_FAILED_MESSAGE, true));
        return;
      }
      this.failPendingStreamFromSocket(
        WEB_SOCKET_STREAM_INTERRUPTED_MESSAGE,
        !this.pendingMessageSent,
        this.pendingMessageSent,
      );
    };

    const onMessage = (evt: MessageEvent) => {
      try {
        const data = JSON.parse(evt.data);
        if (data.type === "sys_notify") {
          this.onSysNotify?.({
            message: String(data.message ?? ""),
            autoTrigger: Boolean(data.auto_trigger),
          });
        } else {
          this.handleEvent(data);
        }
      } catch {
        // Ignore malformed messages.
      }
    };

    const onClose = () => {
      this.ws = null;
      if (!opened) {
        if (settled) return;
        settled = true;
        rejectConnection?.(new WebSocketTransportError(WEB_SOCKET_CONNECTION_FAILED_MESSAGE, true));
        return;
      }
      this.failPendingStreamFromSocket(
        this.pendingMessageSent
          ? WEB_SOCKET_STREAM_INTERRUPTED_MESSAGE
          : WEB_SOCKET_CONNECTION_FAILED_MESSAGE,
        !this.pendingMessageSent,
        this.pendingMessageSent,
      );
    };

    this.ws.addEventListener("open", onOpen);
    this.ws.addEventListener("error", onError);
    this.ws.addEventListener("message", onMessage);
    this.ws.addEventListener("close", onClose);

    this._wsHandlers = { onopen: onOpen, onerror: onError, onmessage: onMessage, onclose: onClose };

    return new Promise<void>((resolve, reject) => {
      resolveConnection = resolve;
      rejectConnection = reject;
    });
  }

  private handleEvent(data: Record<string, unknown>): void {
    const cb = this.pendingCallbacks;
    if (!cb) return;

    switch (data.type) {
      case "assistant_prefix":
        cb.onAssistantPrefix?.(data.text as string);
        break;
      case "reasoning_delta":
        cb.onReasoningDelta?.(data.text as string);
        break;
      case "text_delta":
        cb.onTextDelta?.(data.text as string);
        break;
      case "tool_start":
        cb.onToolStart?.(data.name as string, data.id as string);
        break;
      case "tool_result":
        cb.onToolResult?.(data as ToolCallPayload);
        break;
      case "warning":
        cb.onWarning?.(data.message as string);
        break;
      case "done":
        this._sessionId =
          typeof data.session_id === "string" ? data.session_id : this._sessionId;
        this._conversationId =
          typeof data.conversation_id === "string"
            ? data.conversation_id
            : this._conversationId;
        const assistantMessageId =
          typeof data.message_id === "string" ? data.message_id : null;
        const userMessageId =
          typeof data.user_message_id === "string"
            ? data.user_message_id
            : null;
        if (!this._sessionId || !this._conversationId) {
          cb.onError?.({ message: "Stream completed without session/conversation IDs", code: "MISSING_IDS" });
          break;
        }
        cb.onDone?.(
          this._sessionId,
          this._conversationId,
          assistantMessageId,
          userMessageId,
          data.context as ContextStats | undefined,
          data.persona_state as PersonaState | undefined,
        );
        break;
      case "error":
        cb.onError?.({ message: data.message as string, code: "SERVER_ERROR" });
        break;
    }
  }

  disconnect(): void {
    if (this.ws) {
      if (this._wsHandlers) {
        this.ws.removeEventListener("open", this._wsHandlers.onopen);
        this.ws.removeEventListener("error", this._wsHandlers.onerror);
        this.ws.removeEventListener("message", this._wsHandlers.onmessage);
        this.ws.removeEventListener("close", this._wsHandlers.onclose);
        this._wsHandlers = null;
      }
      this.ws.close();
      this.ws = null;
    }
    this._sessionId = null;
    this._conversationId = null;
  }

  abort(): void {
    const resolve = this.pendingResolve;
    this.resetPendingStream();
    if (this.ws) {
      if (this._wsHandlers) {
        this.ws.removeEventListener("open", this._wsHandlers.onopen);
        this.ws.removeEventListener("error", this._wsHandlers.onerror);
        this.ws.removeEventListener("message", this._wsHandlers.onmessage);
        this.ws.removeEventListener("close", this._wsHandlers.onclose);
        this._wsHandlers = null;
      }
      this.ws.close();
      this.ws = null;
    }
    resolve?.();
  }

  async health(): Promise<boolean> {
    try {
      const resp = await fetch(`${this.baseUrl}/health`);
      return resp.ok;
    } catch {
      return false;
    }
  }

  async reloadConfig(adminToken: string): Promise<ReloadConfigResult> {
    try {
      const resp = await fetch(`${this.baseUrl}/admin/reload`, {
        method: "POST",
        headers: {
          "X-Crabby-Admin-Token": adminToken,
        },
      });
      if (!resp.ok) {
        return {
          ok: false,
          status: resp.status,
          detail: await readErrorDetail(resp),
        };
      }
      return { ok: true, status: resp.status, detail: null };
    } catch {
      return { ok: false, status: null, detail: null };
    }
  }

  async reloadSettings(adminToken: string): Promise<ReloadConfigResult> {
    try {
      const resp = await fetch(`${this.baseUrl}/admin/reload-settings`, {
        method: "POST",
        headers: {
          "X-Crabby-Admin-Token": adminToken,
        },
      });
      if (!resp.ok) {
        return {
          ok: false,
          status: resp.status,
          detail: await readErrorDetail(resp),
        };
      }
      return { ok: true, status: resp.status, detail: null };
    } catch {
      return { ok: false, status: null, detail: null };
    }
  }

  async getMcpStatus(adminToken: string): Promise<MCPStatusResult> {
    try {
      const resp = await fetch(`${this.baseUrl}/admin/mcp/status`, {
        headers: {
          "X-Crabby-Admin-Token": adminToken,
        },
      });
      if (!resp.ok) {
        return {
          ok: false,
          status: resp.status,
          detail: await readErrorDetail(resp),
        };
      }
      return {
        ok: true,
        status: resp.status,
        detail: null,
        data: (await resp.json()) as MCPRuntimeStatus,
      };
    } catch {
      return { ok: false, status: null, detail: null };
    }
  }

  async testCurrentProfile(adminToken: string): Promise<ProfileTestResult> {
    try {
      const resp = await fetch(`${this.baseUrl}/admin/profile/test`, {
        method: "POST",
        headers: {
          "X-Crabby-Admin-Token": adminToken,
        },
      });
      if (!resp.ok) {
        return {
          ok: false,
          status: resp.status,
          detail: await readErrorDetail(resp),
        };
      }
      return {
        ok: true,
        status: resp.status,
        detail: null,
        data: (await resp.json()) as ProfileTestResponse,
      };
    } catch {
      return { ok: false, status: null, detail: null };
    }
  }

  async listLlmProfiles(adminToken: string): Promise<BackendLlmProfilesResult> {
    return this.requestLlmProfiles("/admin/profiles", adminToken);
  }

  async saveLlmProfile(
    adminToken: string,
    profile: BackendLlmProfile,
    activate: boolean,
  ): Promise<BackendLlmProfilesResult> {
    return this.requestLlmProfiles(`/admin/profiles/${profile.id}`, adminToken, {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
        "X-Crabby-Admin-Token": adminToken,
      },
      body: JSON.stringify({ profile, activate }),
    });
  }

  async activateLlmProfile(
    adminToken: string,
    profileId: string,
  ): Promise<BackendLlmProfilesResult> {
    return this.requestLlmProfiles(
      `/admin/profiles/${profileId}/activate`,
      adminToken,
      { method: "POST" },
    );
  }

  async deleteLlmProfile(
    adminToken: string,
    profileId: string,
  ): Promise<BackendLlmProfilesResult> {
    return this.requestLlmProfiles(`/admin/profiles/${profileId}`, adminToken, {
      method: "DELETE",
    });
  }

  private async requestLlmProfiles(
    path: string,
    adminToken: string,
    init: RequestInit = {},
  ): Promise<BackendLlmProfilesResult> {
    try {
      const headers = new Headers(init.headers);
      headers.set("X-Crabby-Admin-Token", adminToken);
      const resp = await fetch(`${this.baseUrl}${path}`, {
        ...init,
        headers,
      });
      if (!resp.ok) {
        return {
          ok: false,
          status: resp.status,
          detail: await readErrorDetail(resp),
        };
      }
      return {
        ok: true,
        status: resp.status,
        detail: null,
        data: (await resp.json()) as BackendLlmProfilesResponse,
      };
    } catch {
      return { ok: false, status: null, detail: null };
    }
  }

  private normalizePayload(
    payload: string | ChatRequestPayload,
    sessionId: string,
    conversationId: string,
  ): ChatRequestPayload {
    if (typeof payload === "string") {
      return {
        content: payload,
        session_id: sessionId,
        conversation_id: conversationId,
      };
    }
    return {
      ...payload,
      session_id: payload.session_id ?? sessionId,
      conversation_id: payload.conversation_id ?? conversationId,
    };
  }

  private normalizeWebSocketPayload(
    payload: string | ChatRequestPayload,
  ): Record<string, unknown> {
    if (typeof payload === "string") {
      return { type: "message", content: payload };
    }
    return {
      type: "message",
      content: payload.content,
      pasted_contents: payload.pasted_contents,
      persona_mode: payload.persona_mode,
      manual_persona_id: payload.manual_persona_id,
    };
  }

  private async ensureSession(): Promise<{
    id: string;
    active_conversation_id: string;
  }> {
    if (this._sessionId && this._conversationId) {
      return {
        id: this._sessionId,
        active_conversation_id: this._conversationId,
      };
    }

    return this.createSession();
  }

  private applySessionInfo(session: SessionInfo): void {
    this._sessionId = session.id;
    this._conversationId = session.active_conversation_id;
  }

  private applyChatResponse(response: ChatResponse): void {
    this._sessionId = response.session_id;
    this._conversationId = response.conversation_id;
  }
}

async function readErrorDetail(resp: Response): Promise<string> {
  try {
    const body = await resp.json();
    if (typeof body?.detail === "string") {
      return body.detail;
    }
    if (typeof body?.message === "string") {
      return body.message;
    }
  } catch {
    // Fall through to response text.
  }

  try {
    return (await resp.text()).trim();
  } catch {
    return "";
  }
}
