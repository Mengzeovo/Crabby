export type ConnectionState = "disconnected" | "connecting" | "connected" | "error";

export type EntryKind = "message" | "tool";
export type MessageRole = "user" | "assistant" | "status";

export interface WindowPoint {
  x: number;
  y: number;
}

export interface PetSettings {
  backendUrl: string;
  launchOnLogin: boolean;
  alwaysOnTop: boolean;
  petPosition: WindowPoint | null;
  petScale: number;
  avatarAsset: string;
  showDockIcon: boolean;
  primaryConversationId: string;
}

export interface MessageAttachment {
  type: string;
  attachment_id?: string;
  path?: string;
  filename?: string;
  preview_url?: string;
}

export interface UserCommand {
  name: string;
  args: string;
}

export interface SessionMessage {
  role: string;
  content?: unknown;
  text?: string;
  model_text?: string;
  command?: UserCommand;
  attachments?: MessageAttachment[];
}

export interface SessionInfo {
  id: string;
  title: string;
  turn_count: number;
  message_count: number;
  created_at: number;
  last_activity_at?: number;
  root_conversation_id?: string;
  active_conversation_id: string;
  branch_fingerprint?: string;
}

export interface ActualTokenUsage {
  call_count: number;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  reasoning_tokens: number;
  cache_creation_input_tokens: number;
  cache_read_input_tokens: number;
}

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
}

export interface TextTranscriptEntry {
  id: string;
  kind: "message";
  role: MessageRole;
  text: string;
  attachments?: MessageAttachment[];
  streaming?: boolean;
}

export interface ToolTranscriptEntry {
  id: string;
  kind: "tool";
  name: string;
  output: string;
  status: "running" | "done";
}

export type TranscriptEntry = TextTranscriptEntry | ToolTranscriptEntry;

export interface BubbleState {
  visible: boolean;
  message: string;
  autoTrigger: boolean;
}

export interface ConversationSnapshot {
  conversationId: string;
  activeConversationId: string;
  title: string;
  entries: TranscriptEntry[];
  isStreaming: boolean;
  unreadCount: number;
  connectionState: ConnectionState;
  lastError: string | null;
  bubble: BubbleState;
  lastContext: ContextStats | null;
}

export interface ChatRequestPayload {
  content: string;
  session_id: string;
  conversation_id: string;
}

export interface StreamDonePayload {
  sessionId: string;
  conversationId: string;
  context?: ContextStats;
}

export interface StreamCallbacks {
  onAssistantPrefix?: (text: string) => void;
  onTextDelta?: (text: string) => void;
  onToolStart?: (name: string, id: string) => void;
  onToolResult?: (name: string, output: string) => void;
  onDone?: (payload: StreamDonePayload) => void;
  onError?: (message: string) => void;
  onWarning?: (message: string) => void;
}

export interface SystemNotificationEvent {
  message: string;
  autoTrigger: boolean;
}

export interface PetWindowEnvironment {
  platform: NodeJS.Platform;
  isMac: boolean;
}

export interface ElectronDesktopApi {
  getEnvironment(): Promise<PetWindowEnvironment>;
  getConversationSnapshot(): Promise<ConversationSnapshot>;
  subscribeConversationSnapshot(
    callback: (snapshot: ConversationSnapshot) => void,
  ): () => void;
  sendChatMessage(content: string): Promise<void>;
  abortChat(): Promise<void>;
  openChatWindow(): Promise<void>;
  openSettingsWindow(): Promise<void>;
  dismissBubble(): Promise<void>;
  getSettings(): Promise<PetSettings>;
  updateSettings(next: Partial<PetSettings>): Promise<PetSettings>;
  subscribeSettings(callback: (settings: PetSettings) => void): () => void;
  resolveAvatarUrl(asset?: string): Promise<string>;
  beginPetDrag(payload: WindowPoint): Promise<void>;
  updatePetDrag(payload: WindowPoint): Promise<void>;
  endPetDrag(payload: WindowPoint): Promise<void>;
  notifyPetClick(): Promise<void>;
  markChatSeen(): Promise<void>;
}
