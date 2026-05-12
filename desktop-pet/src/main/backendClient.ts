import { EventEmitter } from "node:events";

import WebSocket from "ws";

import type {
  ChatRequestPayload,
  ConnectionState,
  ContextStats,
  SessionInfo,
  SessionMessage,
  StreamCallbacks,
  SystemNotificationEvent,
} from "../shared/types";

interface BackendClientEvents {
  connection: (state: ConnectionState, error?: string | null) => void;
  notification: (event: SystemNotificationEvent) => void;
}

type EventKey = keyof BackendClientEvents;

export class BackendRequestError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "BackendRequestError";
  }
}

export class BackendClient {
  private readonly events = new EventEmitter();
  private ws: WebSocket | null = null;
  private connectPromise: Promise<void> | null = null;
  private reconnectTimer: NodeJS.Timeout | null = null;
  private pendingCallbacks: StreamCallbacks | null = null;
  private pendingResolve: (() => void) | null = null;
  private pendingReject: ((error: Error) => void) | null = null;
  private currentSessionId = "";
  private currentConversationId = "";
  private connectionState: ConnectionState = "disconnected";
  private lastError: string | null = null;
  private keepAlive = true;
  private suppressPendingError = false;

  constructor(private baseUrl: string) {}

  on<K extends EventKey>(event: K, handler: BackendClientEvents[K]): () => void {
    this.events.on(event, handler);
    return () => {
      this.events.off(event, handler);
    };
  }

  getState(): { state: ConnectionState; error: string | null } {
    return {
      state: this.connectionState,
      error: this.lastError,
    };
  }

  setBaseUrl(nextBaseUrl: string): void {
    const normalized = nextBaseUrl.trim();
    if (!normalized || normalized === this.baseUrl) {
      return;
    }
    this.baseUrl = normalized;
    void this.reconnect();
  }

  setConversationContext(sessionId: string, conversationId: string): void {
    if (
      !sessionId ||
      !conversationId ||
      (sessionId === this.currentSessionId && conversationId === this.currentConversationId)
    ) {
      return;
    }
    this.currentSessionId = sessionId;
    this.currentConversationId = conversationId;
    void this.reconnect();
  }

  async ensureConnected(): Promise<void> {
    await this.ensureWebSocket();
  }

  async getSessionInfo(sessionId: string): Promise<SessionInfo> {
    return this.fetchJson<SessionInfo>(
      this.buildHttpUrl(`/sessions/${encodeURIComponent(sessionId)}`),
    );
  }

  async createSession(sessionId: string): Promise<SessionInfo> {
    return this.fetchJson<SessionInfo>(this.buildHttpUrl("/sessions"), {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ session_id: sessionId }),
    });
  }

  async getSessionMessages(
    sessionId: string,
    conversationId: string,
  ): Promise<SessionMessage[]> {
    return this.fetchJson<SessionMessage[]>(
      this.buildHttpUrl(
        `/sessions/${encodeURIComponent(sessionId)}/conversations/${encodeURIComponent(conversationId)}/messages`,
      ),
    );
  }

  async streamChat(payload: ChatRequestPayload, callbacks: StreamCallbacks): Promise<void> {
    if (this.pendingCallbacks) {
      throw new Error("A chat turn is already running.");
    }

    this.setConversationContext(payload.session_id, payload.conversation_id);
    await this.ensureWebSocket();

    return new Promise<void>((resolve, reject) => {
      this.pendingCallbacks = callbacks;
      this.pendingResolve = resolve;
      this.pendingReject = reject;

      this.ws?.send(
        JSON.stringify({
          type: "message",
          content: payload.content,
        }),
      );
    });
  }

  abort(): void {
    if (!this.ws) {
      return;
    }
    this.suppressPendingError = true;
    this.ws.close();
    void this.ensureWebSocket().catch(() => {
      // The connection state event already captures the failure.
    });
  }

  disconnect(): void {
    this.keepAlive = false;
    this.clearReconnectTimer();
    this.suppressPendingError = true;
    this.ws?.close();
    this.ws = null;
    this.connectPromise = null;
    this.setConnectionState("disconnected");
  }

  private async reconnect(): Promise<void> {
    this.clearReconnectTimer();
    this.suppressPendingError = true;
    this.ws?.close();
    this.ws = null;
    this.connectPromise = null;
    if (!this.keepAlive) {
      return;
    }
    await this.ensureWebSocket();
  }

  private async ensureWebSocket(): Promise<void> {
    if (!this.currentSessionId || !this.currentConversationId) {
      throw new Error("Missing active session or conversation id.");
    }

    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      return;
    }

    if (this.connectPromise) {
      return this.connectPromise;
    }

    this.connectPromise = new Promise<void>((resolve, reject) => {
      this.setConnectionState("connecting");
      const wsUrl = this.baseUrl.replace(/^http/i, "ws");
      const socket = new WebSocket(
        `${this.buildWebSocketBaseUrl(wsUrl)}/sessions/${encodeURIComponent(this.currentSessionId)}/conversations/${encodeURIComponent(this.currentConversationId)}/ws`,
      );
      this.ws = socket;

      socket.on("open", () => {
        this.lastError = null;
        this.setConnectionState("connected");
        resolve();
      });

      socket.on("message", (buffer) => {
        const raw = typeof buffer === "string" ? buffer : buffer.toString("utf8");
        this.handleSocketMessage(raw);
      });

      socket.on("error", (error) => {
        this.lastError = error instanceof Error ? error.message : String(error);
        this.setConnectionState("error", this.lastError);
        if (this.connectPromise) {
          reject(error instanceof Error ? error : new Error(String(error)));
        }
      });

      socket.on("close", () => {
        const shouldSuppressError = this.suppressPendingError;
        this.suppressPendingError = false;
        this.ws = null;
        this.connectPromise = null;
        this.setConnectionState("disconnected");

        if (this.pendingCallbacks) {
          const resolvePending = this.pendingResolve;
          const rejectPending = this.pendingReject;
          const callbacks = this.pendingCallbacks;
          this.pendingCallbacks = null;
          this.pendingResolve = null;
          this.pendingReject = null;

          if (shouldSuppressError) {
            resolvePending?.();
          } else {
            callbacks.onError?.("WebSocket connection was closed.");
            rejectPending?.(new Error("WebSocket connection was closed."));
          }
        }

        if (this.keepAlive) {
          this.scheduleReconnect();
        }
      });
    });

    return this.connectPromise;
  }

  private scheduleReconnect(): void {
    if (this.reconnectTimer) {
      return;
    }
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      void this.ensureWebSocket().catch(() => {
        // Surface through connection state updates; try again later.
        this.scheduleReconnect();
      });
    }, 1200);
  }

  private clearReconnectTimer(): void {
    if (!this.reconnectTimer) {
      return;
    }
    clearTimeout(this.reconnectTimer);
    this.reconnectTimer = null;
  }

  private handleSocketMessage(raw: string): void {
    let payload: Record<string, unknown>;
    try {
      payload = JSON.parse(raw) as Record<string, unknown>;
    } catch {
      return;
    }

    if (payload.type === "sys_notify") {
      this.events.emit("notification", {
        message: String(payload.message ?? ""),
        autoTrigger: Boolean(payload.auto_trigger),
      });
      return;
    }

    const callbacks = this.pendingCallbacks;
    if (!callbacks) {
      return;
    }

    switch (payload.type) {
      case "assistant_prefix":
        callbacks.onAssistantPrefix?.(String(payload.text ?? ""));
        break;
      case "text_delta":
        callbacks.onTextDelta?.(String(payload.text ?? ""));
        break;
      case "tool_start":
        callbacks.onToolStart?.(String(payload.name ?? ""), String(payload.id ?? ""));
        break;
      case "tool_result":
        callbacks.onToolResult?.(
          String(payload.name ?? ""),
          String(payload.output ?? ""),
        );
        break;
      case "warning":
        callbacks.onWarning?.(String(payload.message ?? ""));
        break;
      case "done": {
        const resolvePending = this.pendingResolve;
        this.pendingCallbacks = null;
        this.pendingResolve = null;
        this.pendingReject = null;
        callbacks.onDone?.(
          {
            sessionId: String(payload.session_id ?? this.currentSessionId),
            conversationId: String(payload.conversation_id ?? this.currentConversationId),
            context: payload.context as ContextStats | undefined,
          },
        );
        resolvePending?.();
        break;
      }
      case "error": {
        const rejectPending = this.pendingReject;
        this.pendingCallbacks = null;
        this.pendingResolve = null;
        this.pendingReject = null;
        const message = String(payload.message ?? "Unknown backend error.");
        callbacks.onError?.(message);
        rejectPending?.(new Error(message));
        break;
      }
      default:
        break;
    }
  }

  private setConnectionState(state: ConnectionState, error?: string | null): void {
    this.connectionState = state;
    if (error !== undefined) {
      this.lastError = error;
    }
    this.events.emit("connection", this.connectionState, this.lastError);
  }

  private buildHttpUrl(pathname: string): string {
    return `${this.baseUrl.replace(/\/+$/, "")}${pathname}`;
  }

  private buildWebSocketBaseUrl(wsUrl: string): string {
    return wsUrl.replace(/\/+$/, "");
  }

  private async fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
    const response = await fetch(url, init);
    if (!response.ok) {
      const detail = await response.text();
      throw new BackendRequestError(
        response.status,
        detail || `Backend request failed: ${response.status}`,
      );
    }
    return (await response.json()) as T;
  }
}
