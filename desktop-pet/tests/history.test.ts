import { describe, expect, it } from "vitest";

import { restoreTranscriptFromSessionMessages } from "../src/shared/history";

describe("restoreTranscriptFromSessionMessages", () => {
  it("restores assistant text, user messages, and tool results in order", () => {
    const transcript = restoreTranscriptFromSessionMessages([
      {
        role: "user",
        text: "hello",
      },
      {
        role: "assistant",
        content: [
          { type: "text", text: "Let me look that up." },
          {
            type: "tool_use",
            id: "tool-1",
            name: "fetch",
            input: { url: "https://example.com" },
          },
        ],
      },
      {
        role: "user",
        content: [
          {
            type: "tool_result",
            tool_use_id: "tool-1",
            content: "Fetched output",
          },
        ],
      },
      {
        role: "assistant",
        content: [{ type: "text", text: "Here is the summary." }],
      },
    ]);

    expect(transcript).toHaveLength(4);
    expect(transcript[0]).toMatchObject({ kind: "message", role: "user", text: "hello" });
    expect(transcript[1]).toMatchObject({
      kind: "message",
      role: "assistant",
      text: "Let me look that up.",
    });
    expect(transcript[2]).toMatchObject({
      kind: "tool",
      name: "fetch",
      output: "Fetched output",
      status: "done",
    });
    expect(transcript[3]).toMatchObject({
      kind: "message",
      role: "assistant",
      text: "Here is the summary.",
    });
  });
});
