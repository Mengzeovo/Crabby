import { describe, expect, it } from "vitest";

import { AUTO_TRIGGER_MESSAGE } from "../src/shared/constants";
import { ConversationManager, type ConversationBackend } from "../src/main/conversationManager";
import type {
  ChatRequestPayload,
  ConnectionState,
  SessionInfo,
  StreamCallbacks,
} from "../src/shared/types";

class MockBackend implements ConversationBackend {
  private connectionHandlers = new Set<
    (state: ConnectionState, error?: string | null) => void
  >();
  private notificationHandlers = new Set<
    (event: { message: string; autoTrigger: boolean }) => void
  >();

  public readonly payloads: ChatRequestPayload[] = [];
  public readonly callbacks: StreamCallbacks[] = [];
  public readonly contexts: Array<{ sessionId: string; conversationId: string }> = [];
  public readonly messageRequests: Array<{ sessionId: string; conversationId: string }> = [];
  public missingSession = false;
  public createdSessionIds: string[] = [];

  on(
    event: "connection" | "notification",
    handler:
      | ((state: ConnectionState, error?: string | null) => void)
      | ((payload: { message: string; autoTrigger: boolean }) => void),
  ): () => void {
    if (event === "connection") {
      const typed = handler as (state: ConnectionState, error?: string | null) => void;
      this.connectionHandlers.add(typed);
      return () => this.connectionHandlers.delete(typed);
    }

    const typed = handler as (payload: { message: string; autoTrigger: boolean }) => void;
    this.notificationHandlers.add(typed);
    return () => this.notificationHandlers.delete(typed);
  }

  setBaseUrl(): void {}
  setConversationContext(sessionId: string, conversationId: string): void {
    this.contexts.push({ sessionId, conversationId });
  }

  async getSessionInfo(sessionId: string): Promise<SessionInfo> {
    if (this.missingSession) {
      this.missingSession = false;
      throw { status: 404 };
    }
    return {
      id: sessionId,
      title: "Recovered session",
      turn_count: 0,
      message_count: 0,
      created_at: 0,
      active_conversation_id: "branch-1",
    };
  }

  async createSession(sessionId: string): Promise<SessionInfo> {
    this.createdSessionIds.push(sessionId);
    return {
      id: sessionId,
      title: "Created session",
      turn_count: 0,
      message_count: 0,
      created_at: 0,
      active_conversation_id: "root",
    };
  }

  async getSessionMessages(sessionId: string, conversationId: string): Promise<any[]> {
    this.messageRequests.push({ sessionId, conversationId });
    return [];
  }

  async ensureConnected(): Promise<void> {
    this.emitConnection("connected");
  }

  async streamChat(payload: ChatRequestPayload, callbacks: StreamCallbacks): Promise<void> {
    this.payloads.push(payload);
    this.callbacks.push(callbacks);
  }

  abort(): void {}
  disconnect(): void {}

  getState(): { state: ConnectionState; error: string | null } {
    return { state: "disconnected", error: null };
  }

  emitConnection(state: ConnectionState, error?: string | null): void {
    for (const handler of this.connectionHandlers) {
      handler(state, error);
    }
  }

  emitNotification(message: string, autoTrigger: boolean): void {
    for (const handler of this.notificationHandlers) {
      handler({ message, autoTrigger });
    }
  }

  async resolveStream(index: number): Promise<void> {
    this.callbacks[index]?.onDone?.({
      sessionId: "conversation-1",
      conversationId: "branch-1",
    });
    await Promise.resolve();
    await Promise.resolve();
  }
}

describe("ConversationManager", () => {
  it("initializes the session branch context and restores branch history", async () => {
    const backend = new MockBackend();
    const manager = new ConversationManager(backend, "conversation-1");

    const snapshot = await manager.initialize();

    expect(snapshot.conversationId).toBe("conversation-1");
    expect(snapshot.activeConversationId).toBe("branch-1");
    expect(backend.contexts[0]).toEqual({
      sessionId: "conversation-1",
      conversationId: "branch-1",
    });
    expect(backend.messageRequests[0]).toEqual({
      sessionId: "conversation-1",
      conversationId: "branch-1",
    });
  });

  it("creates a missing session before connecting to its active branch", async () => {
    const backend = new MockBackend();
    backend.missingSession = true;
    const manager = new ConversationManager(backend, "conversation-1");

    const snapshot = await manager.initialize();

    expect(backend.createdSessionIds).toEqual(["conversation-1"]);
    expect(snapshot.title).toBe("Created session");
    expect(snapshot.activeConversationId).toBe("root");
    expect(backend.contexts[0]).toEqual({
      sessionId: "conversation-1",
      conversationId: "root",
    });
  });

  it("auto-resumes immediately for auto-trigger notifications when idle", async () => {
    const backend = new MockBackend();
    const manager = new ConversationManager(backend, "conversation-1");
    await manager.initialize();

    backend.emitNotification("Background task finished.", true);

    expect(backend.payloads).toHaveLength(1);
    expect(backend.payloads[0].content).toBe(AUTO_TRIGGER_MESSAGE);
    expect(backend.payloads[0]).toMatchObject({
      session_id: "conversation-1",
      conversation_id: "branch-1",
    });
    expect(manager.getSnapshot().bubble).toMatchObject({
      visible: true,
      autoTrigger: true,
    });
  });

  it("queues auto-resume until the current stream finishes", async () => {
    const backend = new MockBackend();
    const manager = new ConversationManager(backend, "conversation-1");
    await manager.initialize();

    await manager.sendUserMessage("hello");
    expect(backend.payloads).toHaveLength(1);

    backend.emitNotification("Task done while busy.", true);
    expect(backend.payloads).toHaveLength(1);

    await backend.resolveStream(0);
    expect(backend.payloads).toHaveLength(2);
    expect(backend.payloads[1].content).toBe(AUTO_TRIGGER_MESSAGE);
    expect(backend.payloads[1]).toMatchObject({
      session_id: "conversation-1",
      conversation_id: "branch-1",
    });
  });
});
