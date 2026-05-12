import type { AddressInfo } from "node:net";

import { describe, expect, it } from "vitest";
import { WebSocketServer } from "ws";

import { BackendClient } from "../src/main/backendClient";

function closeServer(server: WebSocketServer): Promise<void> {
  return new Promise((resolve, reject) => {
    server.close((error) => {
      if (error) {
        reject(error);
        return;
      }
      resolve();
    });
  });
}

describe("BackendClient", () => {
  it("connects to the session/conversation WebSocket route", async () => {
    const server = new WebSocketServer({ port: 0 });
    const address = server.address() as AddressInfo;
    const seenUrl = new Promise<string>((resolve) => {
      server.on("connection", (_socket, request) => {
        resolve(request.url ?? "");
      });
    });

    const client = new BackendClient(`http://127.0.0.1:${address.port}`);
    client.setConversationContext("session-1", "branch-1");

    await client.ensureConnected();
    expect(await seenUrl).toBe("/sessions/session-1/conversations/branch-1/ws");

    client.disconnect();
    await closeServer(server);
  });
});
