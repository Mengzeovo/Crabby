import {
  AgentClient,
  type ChatRequestPayload,
  type StreamCallbacks,
  type ToolCallPayload,
} from "../api/client";

export interface ConversationKey {
  sessionId: string;
  conversationId: string;
}

export type TurnRuntimeStatus = "running" | "done" | "error" | "aborted";

export interface RunningTurnHandle {
  readonly sessionId: string;
  readonly conversationId: string;
  readonly status: TurnRuntimeStatus;
  readonly finished: Promise<void>;
  abort(): Promise<void>;
  detach(): void;
}

type StatusListener = () => void;

interface StartTurnOptions {
  sessionId: string;
  conversationId: string;
  payload: ChatRequestPayload;
  callbacks: ManagedTurnCallbacks;
}

interface ManagedTurnCallbacks extends StreamCallbacks {
  onForeground?: () => void;
}

class ManagedRunningTurn implements RunningTurnHandle {
  private readonly client: AgentClient;
  private callbacks: ManagedTurnCallbacks | null;
  private abortRequested = false;
  private currentStatus: TurnRuntimeStatus = "running";
  public finished: Promise<void> = Promise.resolve();

  constructor(
    baseUrl: string,
    public readonly sessionId: string,
    public readonly conversationId: string,
    callbacks: ManagedTurnCallbacks,
    private readonly notifyStatus: () => void,
    private readonly onFinished: () => void,
  ) {
    this.client = new AgentClient(baseUrl);
    this.client.setSession(sessionId, conversationId);
    this.callbacks = callbacks;
  }

  get status(): TurnRuntimeStatus {
    return this.currentStatus;
  }

  start(payload: ChatRequestPayload): void {
    this.finished = this.client
      .streamChat(payload, this.createProxyCallbacks())
      .catch((error) => {
        if (this.currentStatus === "running") {
          this.currentStatus = this.abortRequested ? "aborted" : "error";
          this.notifyStatus();
        }
        throw error;
      })
      .finally(() => {
        if (this.currentStatus === "running") {
          this.currentStatus = this.abortRequested ? "aborted" : "done";
          this.notifyStatus();
        }
        this.client.disconnect();
        this.callbacks = null;
        this.onFinished();
      });
  }

  detach(): void {
    this.callbacks = null;
  }

  resumeForeground(): void {
    this.callbacks?.onForeground?.();
  }

  async abort(): Promise<void> {
    this.abortRequested = true;
    await this.client.abort();
    if (this.currentStatus === "running") {
      this.currentStatus = "aborted";
      this.notifyStatus();
    }
  }

  private createProxyCallbacks(): StreamCallbacks {
    return {
      onAssistantPrefix: (text: string) => {
        this.callbacks?.onAssistantPrefix?.(text);
      },
      onReasoningDelta: (text: string) => {
        this.callbacks?.onReasoningDelta?.(text);
      },
      onTextDelta: (text: string) => {
        this.callbacks?.onTextDelta?.(text);
      },
      onToolStart: (name: string, id: string) => {
        this.callbacks?.onToolStart?.(name, id);
      },
      onToolResult: (payload: ToolCallPayload) => {
        this.callbacks?.onToolResult?.(payload);
      },
      onWarning: (message: string) => {
        this.callbacks?.onWarning?.(message);
      },
      onDone: (
        sessionId,
        conversationId,
        assistantMessageId,
        userMessageId,
        context,
        personaState,
      ) => {
        this.currentStatus = "done";
        this.notifyStatus();
        this.callbacks?.onDone?.(
          sessionId,
          conversationId,
          assistantMessageId,
          userMessageId,
          context,
          personaState,
        );
      },
      onError: (payload) => {
        this.currentStatus = this.abortRequested ? "aborted" : "error";
        this.notifyStatus();
        this.callbacks?.onError?.(payload);
      },
    };
  }
}

export class ChatTurnManager {
  private turns = new Map<string, ManagedRunningTurn>();
  private terminalStatuses = new Map<string, TurnRuntimeStatus>();
  private currentKey: string | null = null;
  private listeners = new Set<StatusListener>();

  constructor(private baseUrl: string) {}

  setBaseUrl(baseUrl: string): void {
    this.baseUrl = baseUrl;
  }

  keyOf(sessionId: string, conversationId: string): string {
    return `${sessionId}:${conversationId}`;
  }

  addStatusListener(listener: StatusListener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  setCurrentConversation(
    sessionId: string | null,
    conversationId: string | null,
  ): void {
    if (!sessionId || !conversationId) {
      this.currentKey = null;
      this.notifyStatus();
      return;
    }
    const nextKey = this.keyOf(sessionId, conversationId);
    this.currentKey = nextKey;
    this.turns.get(nextKey)?.resumeForeground();
    this.notifyStatus();
  }

  detachCurrent(): void {
    if (!this.currentKey) {
      return;
    }
    this.turns.get(this.currentKey)?.detach();
  }

  startTurn(options: StartTurnOptions): RunningTurnHandle | null {
    if (this.hasRunningSession(options.sessionId)) {
      return null;
    }
    const key = this.keyOf(options.sessionId, options.conversationId);
    const turn = new ManagedRunningTurn(
      this.baseUrl,
      options.sessionId,
      options.conversationId,
      options.callbacks,
      () => this.notifyStatus(),
      () => {
        this.turns.delete(key);
        this.terminalStatuses.set(key, turn.status);
        this.notifyStatus();
      },
    );
    this.turns.set(key, turn);
    this.terminalStatuses.delete(key);
    this.notifyStatus();
    turn.start(options.payload);
    return turn;
  }

  getStatus(
    sessionId: string | null,
    conversationId: string | null,
  ): TurnRuntimeStatus | null {
    if (!sessionId || !conversationId) {
      return null;
    }
    const key = this.keyOf(sessionId, conversationId);
    return this.turns.get(key)?.status ?? this.terminalStatuses.get(key) ?? null;
  }

  getSessionStatus(sessionId: string): TurnRuntimeStatus | null {
    for (const turn of this.turns.values()) {
      if (turn.sessionId === sessionId) {
        return turn.status;
      }
    }
    for (const [key, status] of this.terminalStatuses.entries()) {
      if (key.startsWith(`${sessionId}:`)) {
        return status;
      }
    }
    return null;
  }

  isRunning(
    sessionId: string | null,
    conversationId: string | null,
  ): boolean {
    return this.getStatus(sessionId, conversationId) === "running";
  }

  hasRunningSession(sessionId: string | null): boolean {
    if (!sessionId) {
      return false;
    }
    for (const turn of this.turns.values()) {
      if (turn.sessionId === sessionId && turn.status === "running") {
        return true;
      }
    }
    return false;
  }

  isCurrent(sessionId: string, conversationId: string): boolean {
    return this.currentKey === this.keyOf(sessionId, conversationId);
  }

  async abort(
    sessionId: string | null,
    conversationId: string | null,
  ): Promise<void> {
    if (!sessionId || !conversationId) {
      return;
    }
    await this.turns.get(this.keyOf(sessionId, conversationId))?.abort();
  }

  clearTerminalStatus(sessionId: string, conversationId: string): void {
    const key = this.keyOf(sessionId, conversationId);
    if (this.terminalStatuses.delete(key)) {
      this.notifyStatus();
    }
  }

  consumeTerminalStatus(
    sessionId: string,
    conversationId: string,
  ): TurnRuntimeStatus | null {
    const key = this.keyOf(sessionId, conversationId);
    const status = this.terminalStatuses.get(key) ?? null;
    if (status) {
      this.terminalStatuses.delete(key);
      this.notifyStatus();
    }
    return status;
  }

  destroy(): void {
    for (const turn of this.turns.values()) {
      turn.detach();
      void turn.abort();
    }
    this.turns.clear();
    this.terminalStatuses.clear();
    this.listeners.clear();
  }

  private notifyStatus(): void {
    for (const listener of this.listeners) {
      listener();
    }
  }
}
