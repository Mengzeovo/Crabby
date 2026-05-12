import type { App, Component } from "obsidian";

import type {
  AgentClient,
  ChatRequestPayload,
  ContextStats,
  ImageAttachment,
  ImagePaste,
  MessageAttachment,
  PersonaState,
  SessionInfo,
  SystemNotificationEvent,
} from "../api/client";
import type LifeAssistantPlugin from "../main";

export type ChatRole = "user" | "assistant" | "status";

export interface ChatMessage {
  role: ChatRole;
  content: string;
  messageId?: string | null;
  attachments?: MessageAttachment[];
}

export interface UserMsgRef {
  dot: HTMLDivElement;
  msgEl: HTMLDivElement;
}

export interface ChatElements {
  messagesEl: HTMLDivElement;
  minimapEl: HTMLDivElement;
  inputAreaEl: HTMLDivElement;
  inputEl: HTMLTextAreaElement;
  sendBtn: HTMLButtonElement;
  attachmentBtn: HTMLButtonElement;
  hiddenFileInput: HTMLInputElement;
  composerPillsEl: HTMLDivElement;
  suggestionListEl: HTMLDivElement;
  contextBarEl: HTMLDivElement;
  sessionTitleEl: HTMLDivElement;
  sessionPanelEl: HTMLDivElement;
  sessionListEl: HTMLDivElement;
  treePanelEl: HTMLDivElement;
  treePanelTitleEl: HTMLSpanElement;
  treeListEl: HTMLDivElement;
}

export interface ChatViewState {
  messages: ChatMessage[];
  userMsgRefs: UserMsgRef[];
  toolBlocks: Map<string, HTMLDivElement>;
  toolIdToName: Map<string, string>;
  isSending: boolean;
  isAborted: boolean;
  sessionPanelOpen: boolean;
  treePanelOpen: boolean;
  personaState: PersonaState;
}

export interface ChatCommonDeps {
  app: App;
  component: Component;
  client: AgentClient;
  plugin: LifeAssistantPlugin;
  elements: ChatElements;
  state: ChatViewState;
}

export interface LocalImageAttachment extends ImageAttachment {
  preview_url: string;
}

export interface ChatComposerSubmitPayload {
  request: ChatRequestPayload;
  displayText: string;
  displayAttachments: MessageAttachment[];
}

export interface ChatComposerController {
  getSubmitPayload(): ChatComposerSubmitPayload | null;
  navigateHistory(direction: "up" | "down"): boolean;
  clear(): void;
  destroy(): void;
}

export interface ChatTranscriptController {
  appendMessage(
    role: ChatRole,
    content: string,
    forceScroll?: boolean,
    attachments?: MessageAttachment[],
    messageId?: string | null,
  ): void;
  renderAssistantMessage(
    targetEl: HTMLElement,
    content: string,
    messageId?: string | null,
  ): void;
  updateLastUserMessageId(messageId?: string | null): boolean;
  beginTool(name: string, id: string): void;
  completeTool(name: string, output: string): void;
  renderHistoricalTool(name: string, output: string): void;
  clearConversationUi(): void;
  clearToolTracking(): void;
  removeTransientUi(): void;
  scrollToBottom(force?: boolean): void;
  updateContextBar(ctx: ContextStats): void;
  setForkHandler(handler: ForkMessageHandler | null): void;
}

export interface ChatSessionsController {
  handleNewSession(): void;
  toggleSessionPanel(): void;
  toggleTreePanel(): void;
  loadSessionList(): Promise<void>;
  loadConversationTree(): Promise<void>;
  switchToSession(session: SessionInfo): Promise<void>;
  deleteSessionConfirm(sessionId: string): Promise<void>;
  syncCurrentSessionTitle(sessionId: string): Promise<void>;
}

export interface ForkMessageTarget {
  messageId: string;
  content: string;
  role: ChatRole;
}

export type ForkMessageHandler = (target: ForkMessageTarget) => void | Promise<void>;

export interface ChatPersonaController {
  setPersonaState(nextState: PersonaState): void;
}

export interface ChatTurnRunnerController {
  handleSend(overrideText?: string): Promise<void>;
  handleStop(): void;
  handleSysNotify(event: SystemNotificationEvent): void;
}

export interface TranscriptDeps extends ChatCommonDeps {}

export interface SessionDeps extends ChatCommonDeps {
  composer: ChatComposerController;
  transcript: ChatTranscriptController;
  persona: ChatPersonaController;
}

export interface TurnRunnerDeps extends ChatCommonDeps {
  composer: ChatComposerController;
  transcript: ChatTranscriptController;
  sessions: ChatSessionsController;
  persona: ChatPersonaController;
}

export type ChatCleanup = () => void;

export interface ComposerImagePaste extends ImagePaste {
  preview_url: string;
  size_bytes: number;
}

export type { ContextStats } from "../api/client";
