const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const os = require("node:os");
const path = require("node:path");
const esbuild = require("esbuild");

async function loadApiClientModule() {
  const outdir = await fs.mkdtemp(path.join(os.tmpdir(), "api-client-test-"));
  const outfile = path.join(outdir, "client.cjs");
  await esbuild.build({
    entryPoints: [path.join(__dirname, "../src/api/client.ts")],
    bundle: true,
    format: "cjs",
    platform: "node",
    outfile,
    logLevel: "silent",
  });
  return require(outfile);
}

function nextTick() {
  return new Promise((resolve) => setTimeout(resolve, 0));
}

async function main() {
  const fetchCalls = [];
  let resolveFetch;
  global.fetch = (url, init) => {
    fetchCalls.push({ url: String(url), init });
    return new Promise((resolve) => {
      resolveFetch = () =>
        resolve({
          ok: true,
          json: async () => ({ ok: true, status: "cancelled" }),
          text: async () => "",
        });
    });
  };

  const sockets = [];
  class FakeWebSocket {
    static CONNECTING = 0;
    static OPEN = 1;
    static CLOSED = 3;

    constructor(url) {
      this.url = url;
      this.readyState = FakeWebSocket.CONNECTING;
      this.listeners = new Map();
      this.sent = [];
      this.closed = false;
      sockets.push(this);
      setTimeout(() => {
        this.readyState = FakeWebSocket.OPEN;
        this.emit("open", {});
      }, 0);
    }

    addEventListener(type, handler) {
      const handlers = this.listeners.get(type) || [];
      handlers.push(handler);
      this.listeners.set(type, handlers);
    }

    removeEventListener(type, handler) {
      const handlers = this.listeners.get(type) || [];
      this.listeners.set(
        type,
        handlers.filter((candidate) => candidate !== handler),
      );
    }

    emit(type, event) {
      for (const handler of this.listeners.get(type) || []) {
        handler(event);
      }
    }

    send(message) {
      this.sent.push(String(message));
    }

    close() {
      this.closed = true;
      this.readyState = FakeWebSocket.CLOSED;
    }
  }
  global.WebSocket = FakeWebSocket;

  const { AgentClient } = await loadApiClientModule();
  const client = new AgentClient("http://127.0.0.1:8000");
  client.setSession("session-1", "root");

  let streamResolved = false;
  const streamPromise = client
    .streamChat({ content: "hello" }, {})
    .then(() => {
      streamResolved = true;
    });

  for (let attempt = 0; attempt < 20; attempt += 1) {
    if (sockets[0]?.sent.length) {
      break;
    }
    await nextTick();
  }

  assert.equal(sockets.length, 1);
  assert.equal(sockets[0].sent.length, 1);
  const sentPayload = JSON.parse(sockets[0].sent[0]);
  assert.equal(sentPayload.content, "hello");
  assert.equal(typeof sentPayload.turn_id, "string");
  assert.ok(sentPayload.turn_id.length > 0);

  const abortPromise = client.abort();
  await nextTick();

  assert.equal(streamResolved, false);
  assert.equal(fetchCalls.length, 1);
  assert.match(
    fetchCalls[0].url,
    /\/sessions\/session-1\/conversations\/root\/abort$/,
  );
  assert.deepEqual(JSON.parse(fetchCalls[0].init.body), {
    turn_id: sentPayload.turn_id,
  });
  assert.equal(sockets[0].closed, false);

  resolveFetch();
  await abortPromise;
  await streamPromise;

  assert.equal(streamResolved, true);
  assert.equal(sockets[0].closed, true);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
