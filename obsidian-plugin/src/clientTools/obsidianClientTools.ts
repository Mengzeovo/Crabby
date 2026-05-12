import type CrabbyPlugin from "../main";
import {
  normalizeCrabbySettingsInput,
  performCrabbySettingsAction,
} from "./crabbySettingsTool";
import { performObsidianSearch } from "../search/obsidianSearch";
import type { SearchInput } from "../search/searchEngine";

interface ClientToolRequest {
  type: "client_tool_request";
  request_id: string;
  tool: string;
  input?: unknown;
}

export class ObsidianClientToolBridge {
  private ws: WebSocket | null = null;
  private reconnectTimer: number | null = null;
  private stopped = true;

  constructor(
    private readonly plugin: CrabbyPlugin,
    private readonly getBackendUrl: () => string,
  ) {}

  start(): void {
    this.stopped = false;
    this.connect();
  }

  stop(): void {
    this.stopped = true;
    if (this.reconnectTimer !== null) {
      window.clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
  }

  private connect(): void {
    if (this.stopped || this.ws) {
      return;
    }

    const backendUrl = this.getBackendUrl().trim();
    if (!backendUrl) {
      this.scheduleReconnect();
      return;
    }

    const wsUrl = backendUrl.replace(/^http/i, "ws").replace(/\/$/, "");
    const ws = new WebSocket(`${wsUrl}/client-tools/obsidian`);
    this.ws = ws;

    ws.onmessage = (event) => {
      void this.handleMessage(event.data);
    };
    ws.onclose = () => {
      if (this.ws === ws) {
        this.ws = null;
      }
      this.scheduleReconnect();
    };
    ws.onerror = () => {
      ws.close();
    };
  }

  private scheduleReconnect(): void {
    if (this.stopped || this.reconnectTimer !== null) {
      return;
    }
    this.reconnectTimer = window.setTimeout(() => {
      this.reconnectTimer = null;
      this.connect();
    }, 3000);
  }

  private async handleMessage(raw: string): Promise<void> {
    let request: ClientToolRequest;
    try {
      request = JSON.parse(raw) as ClientToolRequest;
    } catch {
      return;
    }

    if (request.type !== "client_tool_request" || !request.request_id) {
      return;
    }

    try {
      let result: unknown;
      if (request.tool === "obsidian_search") {
        result = await performObsidianSearch(
          this.plugin.app,
          normalizeSearchInput(request.input),
        );
      } else if (request.tool === "crabby_settings") {
        result = await performCrabbySettingsAction(
          this.plugin,
          normalizeCrabbySettingsInput(request.input),
        );
      } else {
        throw new Error(`Unknown client tool: ${request.tool}`);
      }
      this.send({
        type: "client_tool_result",
        request_id: request.request_id,
        result,
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      this.send({
        type: "client_tool_error",
        request_id: request.request_id,
        error: message,
      });
    }
  }

  private send(payload: Record<string, unknown>): void {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      return;
    }
    this.ws.send(JSON.stringify(payload));
  }
}

function normalizeSearchInput(input: unknown): SearchInput {
  if (!input || typeof input !== "object") {
    return { query: "" };
  }
  const record = input as Record<string, unknown>;
  return {
    query: String(record.query ?? ""),
    max_results:
      typeof record.max_results === "number" ? record.max_results : undefined,
    context_chars:
      typeof record.context_chars === "number" ? record.context_chars : undefined,
    sort:
      record.sort === "mtime_desc" ||
      record.sort === "mtime_asc" ||
      record.sort === "path"
        ? record.sort
        : "score",
  };
}
