import { EventEmitter } from "node:events";
import crypto from "node:crypto";

import { AUTO_TRIGGER_MESSAGE, EMPTY_BUBBLE, createEmptySnapshot } from "../shared/constants";
import { restoreTranscriptFromSessionMessages } from "../shared/history";
import type {
  BubbleState,
  ChatRequestPayload,
  ConnectionState,
  ContextStats,
  ConversationSnapshot,
  SessionInfo,
  StreamCallbacks,
  TranscriptEntry,
} from "../shared/types";

export interface ConversationBackend {
  on(
    event: "connection",
    handler: (state: ConnectionState, error?: string | null) => void,
  ): () => void;
  on(
    event: "notification",
    handler: (event: { message: string; autoTrigger: boolean }) => void,
  ): () => void;
  setBaseUrl(nextBaseUrl: string): void;
  setConversationContext(sessionId: string, conversationId: string): void;
  getSessionInfo(sessionId: string): Promise<SessionInfo>;
  createSession(sessionId: string): Promise<SessionInfo>;
  getSessionMessages(sessionId: string, conversationId: string): Promise<any[]>;
  ensureConnected(): Promise<void>;
  streamChat(payload: ChatRequestPayload, callbacks: StreamCallbacks): Promise<void>;
  abort(): void;
  disconnect(): void;
  getState(): { state: ConnectionState; error: string | null };
}

export class ConversationManager {
  private readonly events = new EventEmitter();
  private readonly snapshot: ConversationSnapshot;
  private pendingAutoResume = false;
  private chatVisible = false;
  private currentAssistantId: string | null = null;

  constructor(
    private readonly backend: ConversationBackend,
    conversationId: string,
  ) {
    const normalizedConversationId = conversationId || crypto.randomUUID().slice(0, 12);
    this.snapshot = createEmptySnapshot(normalizedConversationId);

    const backendState = this.backend.getState();
    this.snapshot.connectionState = backendState.state;
    this.snapshot.lastError = backendState.error;

    this.backend.on("connection", (state, error) => {
      this.snapshot.connectionState = state;
      this.snapshot.lastError = error ?? null;
      this.emitSnapshot();
    });
    this.backend.on("notification", (event) => {
      this.handleNotification(event.message, event.autoTrigger);
    });
  }

  async initialize(): Promise<ConversationSnapshot> {
    await this.restoreSession();
    this.backend.setConversationContext(
      this.snapshot.conversationId,
      this.snapshot.activeConversationId,
    );
    await this.backend.ensureConnected();
    this.emitSnapshot();
    return this.getSnapshot();
  }

  updateBackendUrl(nextBaseUrl: string): void {
    this.backend.setBaseUrl(nextBaseUrl);
  }

  getConversationId(): string {
    return this.snapshot.conversationId;
  }

  getSnapshot(): ConversationSnapshot {
    return JSON.parse(JSON.stringify(this.snapshot)) as ConversationSnapshot;
  }

  onSnapshot(handler: (snapshot: ConversationSnapshot) => void): () => void {
    this.events.on("snapshot", handler);
    return () => {
      this.events.off("snapshot", handler);
    };
  }

  setChatVisible(isVisible: boolean): void {
    this.chatVisible = isVisible;
    if (isVisible && this.snapshot.unreadCount > 0) {
      this.snapshot.unreadCount = 0;
      this.emitSnapshot();
    }
  }

  markChatSeen(): void {
    if (this.snapshot.unreadCount === 0) {
      return;
    }
    this.snapshot.unreadCount = 0;
    this.emitSnapshot();
  }

  dismissBubble(): void {
    this.setBubble(EMPTY_BUBBLE);
  }

  async sendUserMessage(content: string): Promise<void> {
    const normalized = content.trim();
    if (!normalized || this.snapshot.isStreaming) {
      return;
    }

    this.currentAssistantId = null;
    this.snapshot.lastError = null;
    this.snapshot.isStreaming = true;
    this.snapshot.entries.push({
      id: this.nextEntryId(),
      kind: "message",
      role: "user",
      text: normalized,
      attachments: [],
    });
    this.emitSnapshot();

    await this.backend.streamChat(
      {
        content: normalized,
        session_id: this.snapshot.conversationId,
        conversation_id: this.snapshot.activeConversationId,
      },
      this.buildCallbacks(),
    );
  }

  abort(): void {
    if (!this.snapshot.isStreaming) {
      return;
    }
    this.snapshot.isStreaming = false;
    this.finalizeStreamingAssistant();
    this.backend.abort();
    this.appendStatus("Current response stopped.");
  }

  shutdown(): void {
    this.backend.disconnect();
  }

  private async restoreSession(): Promise<void> {
    const session = await this.getOrCreateSession();
    this.applySessionInfo(session);

    try {
      const messages = await this.backend.getSessionMessages(
        this.snapshot.conversationId,
        this.snapshot.activeConversationId,
      );
      this.snapshot.entries = restoreTranscriptFromSessionMessages(messages);
    } catch {
      this.snapshot.entries = [];
    }
  }

  private async getOrCreateSession(): Promise<SessionInfo> {
    try {
      return await this.backend.getSessionInfo(this.snapshot.conversationId);
    } catch (error) {
      if (!this.isNotFoundError(error)) {
        throw error;
      }
      return this.backend.createSession(this.snapshot.conversationId);
    }
  }

  private isNotFoundError(error: unknown): boolean {
    return (
      typeof error === "object" &&
      error !== null &&
      "status" in error &&
      (error as { status?: unknown }).status === 404
    );
  }

  private applySessionInfo(session: SessionInfo): void {
    this.snapshot.title = session.title || this.snapshot.title;
    const activeConversationId = session.active_conversation_id?.trim();
    if (!activeConversationId) {
      throw new Error("Backend session response is missing active_conversation_id.");
    }
    this.snapshot.activeConversationId = activeConversationId;
  }

  private buildCallbacks(): StreamCallbacks {
    return {
      onAssistantPrefix: (text) => {
        this.upsertAssistantDelta(text);
      },
      onTextDelta: (text) => {
        this.upsertAssistantDelta(text);
      },
      onToolStart: (name) => {
        this.finalizeStreamingAssistant();
        this.snapshot.entries.push({
          id: this.nextEntryId(),
          kind: "tool",
          name,
          output: "",
          status: "running",
        });
        this.noteUnread();
        this.emitSnapshot();
      },
      onToolResult: (name, output) => {
        const toolEntry = [...this.snapshot.entries]
          .reverse()
          .find(
            (entry): entry is Extract<TranscriptEntry, { kind: "tool" }> =>
              entry.kind === "tool" && entry.name === name && entry.status === "running",
          );

        if (toolEntry) {
          toolEntry.output = output;
          toolEntry.status = "done";
        } else {
          this.snapshot.entries.push({
            id: this.nextEntryId(),
            kind: "tool",
            name,
            output,
            status: "done",
          });
          this.noteUnread();
        }
        this.emitSnapshot();
      },
      onWarning: (message) => {
        this.appendStatus(message);
      },
      onDone: async (result) => {
        this.snapshot.isStreaming = false;
        this.snapshot.activeConversationId = result.conversationId;
        this.backend.setConversationContext(
          result.sessionId,
          this.snapshot.activeConversationId,
        );
        this.finalizeStreamingAssistant();
        this.snapshot.lastContext = (result.context as ContextStats | undefined) ?? null;
        await this.refreshTitle();
        this.emitSnapshot();

        if (this.pendingAutoResume) {
          this.pendingAutoResume = false;
          void this.sendAutoResume();
        }
      },
      onError: (message) => {
        this.snapshot.isStreaming = false;
        this.snapshot.lastError = message;
        this.finalizeStreamingAssistant();
        this.appendStatus(message);
      },
    };
  }

  private async refreshTitle(): Promise<void> {
    try {
      const session = await this.backend.getSessionInfo(this.snapshot.conversationId);
      this.applySessionInfo(session);
      this.backend.setConversationContext(
        this.snapshot.conversationId,
        this.snapshot.activeConversationId,
      );
    } catch {
      // Keep the last known title.
    }
  }

  private handleNotification(message: string, autoTrigger: boolean): void {
    this.appendStatus(message);
    this.setBubble({
      visible: true,
      message,
      autoTrigger,
    });

    if (!autoTrigger) {
      return;
    }

    if (this.snapshot.isStreaming) {
      this.pendingAutoResume = true;
      return;
    }

    void this.sendAutoResume();
  }

  private async sendAutoResume(): Promise<void> {
    if (this.snapshot.isStreaming) {
      this.pendingAutoResume = true;
      return;
    }

    this.snapshot.isStreaming = true;
    this.snapshot.lastError = null;
    this.appendStatus("Background task finished. Continuing the conversation automatically.");

    try {
      await this.backend.streamChat(
        {
          content: AUTO_TRIGGER_MESSAGE,
          session_id: this.snapshot.conversationId,
          conversation_id: this.snapshot.activeConversationId,
        },
        this.buildCallbacks(),
      );
    } catch {
      // Errors are already surfaced by the stream callback.
    }
  }

  private upsertAssistantDelta(delta: string): void {
    if (!this.currentAssistantId) {
      const entry = {
        id: this.nextEntryId(),
        kind: "message" as const,
        role: "assistant" as const,
        text: delta,
        streaming: true,
      };
      this.currentAssistantId = entry.id;
      this.snapshot.entries.push(entry);
      this.noteUnread();
      this.emitSnapshot();
      return;
    }

    const currentEntry = this.snapshot.entries.find(
      (entry): entry is Extract<TranscriptEntry, { kind: "message" }> =>
        entry.kind === "message" && entry.id === this.currentAssistantId,
    );
    if (!currentEntry) {
      this.currentAssistantId = null;
      this.upsertAssistantDelta(delta);
      return;
    }
    currentEntry.text += delta;
    this.emitSnapshot();
  }

  private finalizeStreamingAssistant(): void {
    if (!this.currentAssistantId) {
      return;
    }
    const currentEntry = this.snapshot.entries.find(
      (entry): entry is Extract<TranscriptEntry, { kind: "message" }> =>
        entry.kind === "message" && entry.id === this.currentAssistantId,
    );
    if (currentEntry) {
      currentEntry.streaming = false;
    }
    this.currentAssistantId = null;
  }

  private appendStatus(message: string): void {
    this.snapshot.entries.push({
      id: this.nextEntryId(),
      kind: "message",
      role: "status",
      text: message,
    });
    this.noteUnread();
    this.emitSnapshot();
  }

  private setBubble(bubble: BubbleState): void {
    this.snapshot.bubble = { ...bubble };
    this.noteUnread();
    this.emitSnapshot();
  }

  private noteUnread(): void {
    if (!this.chatVisible) {
      this.snapshot.unreadCount += 1;
    }
  }

  private emitSnapshot(): void {
    this.events.emit("snapshot", this.getSnapshot());
  }

  private nextEntryId(): string {
    return crypto.randomUUID().slice(0, 12);
  }
}
