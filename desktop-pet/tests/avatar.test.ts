import path from "node:path";

import { describe, expect, it } from "vitest";

import { resolveAvatarAssetUrl } from "../src/main/avatar";
import { getDynamicAvatarAsset } from "../src/shared/avatar";

const distRoot = path.join("D:", "tmp", "desktop-pet-dist");

function toFileUrl(...segments: string[]): string {
  return `file://${path.join(distRoot, ...segments).replace(/\\/g, "/")}`;
}

describe("avatar helpers", () => {
  it("maps builtin crabby assets to packaged files", () => {
    expect(resolveAvatarAssetUrl(distRoot, "builtin:crabby")).toBe(
      toFileUrl("assets", "Crabby", "face_normal_fullbody_transparent.png"),
    );
    expect(resolveAvatarAssetUrl(distRoot, "builtin:crabby:happy")).toBe(
      toFileUrl("assets", "Crabby", "face_happy_fullbody_transparent.png"),
    );
    expect(resolveAvatarAssetUrl(distRoot, "builtin:crabby:error")).toBe(
      toFileUrl("assets", "Crabby", "reconnect_error_fullbody_transparent.png"),
    );
    expect(resolveAvatarAssetUrl(distRoot, "builtin:crabby:idle")).toBe(
      toFileUrl("assets", "Crabby", "offline_fullbody_transparent.png"),
    );
  });

  it("keeps custom asset URLs untouched", () => {
    expect(
      resolveAvatarAssetUrl(distRoot, "https://example.com/avatar.png"),
    ).toBe("https://example.com/avatar.png");
  });

  it("chooses crabby variants from live pet state", () => {
    expect(
      getDynamicAvatarAsset("builtin:crabby", {
        isStreaming: false,
        unreadCount: 0,
        connectionState: "connected",
        bubble: { visible: false, message: "", autoTrigger: false },
      }),
    ).toBe("builtin:crabby:normal");

    expect(
      getDynamicAvatarAsset("builtin:crabby", {
        isStreaming: true,
        unreadCount: 0,
        connectionState: "connected",
        bubble: { visible: false, message: "", autoTrigger: false },
      }),
    ).toBe("builtin:crabby:thinking");

    expect(
      getDynamicAvatarAsset("builtin:crabby", {
        isStreaming: false,
        unreadCount: 2,
        connectionState: "connected",
        bubble: { visible: true, message: "hi", autoTrigger: false },
      }),
    ).toBe("builtin:crabby:happy");

    expect(
      getDynamicAvatarAsset("builtin:crabby", {
        isStreaming: false,
        unreadCount: 0,
        connectionState: "error",
        bubble: { visible: false, message: "", autoTrigger: false },
      }),
    ).toBe("builtin:crabby:error");

    expect(
      getDynamicAvatarAsset("builtin:crabby", {
        isStreaming: false,
        unreadCount: 0,
        connectionState: "disconnected",
        bubble: { visible: false, message: "", autoTrigger: false },
      }),
    ).toBe("builtin:crabby:idle");
  });
});
