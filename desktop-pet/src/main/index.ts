import path from "node:path";

import {
  BrowserWindow,
  Menu,
  Tray,
  app,
  ipcMain,
  screen,
} from "electron";

import { resolveAvatarAssetUrl } from "./avatar";
import { BackendClient } from "./backendClient";
import { ConversationManager } from "./conversationManager";
import { createPetTrayIcon } from "./iconFactory";
import { normalizeSettings, SettingsStore } from "./settingsStore";
import { DEFAULT_SETTINGS, EMPTY_BUBBLE } from "../shared/constants";
import type {
  ConversationSnapshot,
  PetSettings,
  PetWindowEnvironment,
  WindowPoint,
} from "../shared/types";

const distRoot = path.resolve(__dirname, "..");
const rendererDir = path.join(distRoot, "renderer");
const preloadPath = path.join(distRoot, "main", "preload.cjs");

let settingsStore: SettingsStore;
let settings: PetSettings = { ...DEFAULT_SETTINGS };
let backendClient: BackendClient;
let conversationManager: ConversationManager;
let tray: Tray | null = null;
let petWindow: BrowserWindow | null = null;
let chatWindow: BrowserWindow | null = null;
let settingsWindow: BrowserWindow | null = null;
let bubbleWindow: BrowserWindow | null = null;
let bubbleTimer: NodeJS.Timeout | null = null;
let activeBubbleKey = "";
let isQuitting = false;
let dragOrigin: { cursor: WindowPoint; window: WindowPoint } | null = null;

function getEnvironment(): PetWindowEnvironment {
  return {
    platform: process.platform,
    isMac: process.platform === "darwin",
  };
}

function getSettingsFilePath(): string {
  return path.join(app.getPath("userData"), "desktop-pet-settings.json");
}

function getPetSize(scale: number): { width: number; height: number } {
  return {
    width: Math.round(164 * scale),
    height: Math.round(192 * scale),
  };
}

function clampToWorkArea(point: WindowPoint, width: number, height: number): WindowPoint {
  const area = screen.getPrimaryDisplay().workArea;
  return {
    x: Math.max(area.x, Math.min(point.x, area.x + area.width - width)),
    y: Math.max(area.y, Math.min(point.y, area.y + area.height - height)),
  };
}

function getDefaultPetPosition(scale: number): WindowPoint {
  const area = screen.getPrimaryDisplay().workArea;
  const { width, height } = getPetSize(scale);
  return {
    x: area.x + area.width - width - 28,
    y: area.y + area.height - height - 28,
  };
}

function getPetPosition(): WindowPoint {
  const { width, height } = getPetSize(settings.petScale);
  const position = settings.petPosition ?? getDefaultPetPosition(settings.petScale);
  return clampToWorkArea(position, width, height);
}

async function persistSettings(): Promise<void> {
  await settingsStore.save(settings);
}

function applyActivationPolicy(): void {
  if (process.platform !== "darwin") {
    return;
  }
  if (settings.showDockIcon) {
    app.setActivationPolicy("regular");
    if (app.dock) {
      void app.dock.show();
    }
  } else {
    app.setActivationPolicy("accessory");
    app.dock?.hide();
  }
}

function applyLoginItemSettings(): void {
  app.setLoginItemSettings({
    openAtLogin: settings.launchOnLogin,
  });
}

function buildWindowUrl(fileName: string): string {
  return path.join(rendererDir, fileName);
}

function createPetWindow(): BrowserWindow {
  if (petWindow) {
    return petWindow;
  }

  const { width, height } = getPetSize(settings.petScale);
  const position = getPetPosition();
  petWindow = new BrowserWindow({
    width,
    height,
    x: position.x,
    y: position.y,
    transparent: true,
    frame: false,
    resizable: false,
    show: false,
    skipTaskbar: true,
    hasShadow: false,
    alwaysOnTop: settings.alwaysOnTop,
    webPreferences: {
      preload: preloadPath,
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  petWindow.loadFile(buildWindowUrl("pet.html"));
  petWindow.once("ready-to-show", () => {
    petWindow?.showInactive();
  });
  petWindow.on("closed", () => {
    petWindow = null;
  });

  return petWindow;
}

function positionChatWindow(window: BrowserWindow): void {
  const petBounds = petWindow?.getBounds();
  if (!petBounds) {
    return;
  }
  const workArea = screen.getDisplayNearestPoint({
    x: petBounds.x,
    y: petBounds.y,
  }).workArea;
  const chatBounds = window.getBounds();
  const x = Math.max(
    workArea.x + 24,
    Math.min(
      petBounds.x - chatBounds.width - 18,
      workArea.x + workArea.width - chatBounds.width - 24,
    ),
  );
  const y = Math.max(
    workArea.y + 24,
    Math.min(
      petBounds.y + Math.round((petBounds.height - chatBounds.height) / 2),
      workArea.y + workArea.height - chatBounds.height - 24,
    ),
  );
  window.setBounds({ ...chatBounds, x, y });
}

function createChatWindow(): BrowserWindow {
  if (chatWindow) {
    return chatWindow;
  }

  chatWindow = new BrowserWindow({
    width: 480,
    height: 720,
    minWidth: 420,
    minHeight: 520,
    show: false,
    backgroundColor: "#f4ede0",
    autoHideMenuBar: true,
    title: "Life Assistant Chat",
    webPreferences: {
      preload: preloadPath,
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  chatWindow.loadFile(buildWindowUrl("chat.html"));
  chatWindow.on("ready-to-show", () => {
    positionChatWindow(chatWindow!);
  });
  chatWindow.on("show", () => {
    conversationManager.setChatVisible(true);
  });
  chatWindow.on("focus", () => {
    conversationManager.setChatVisible(true);
  });
  chatWindow.on("hide", () => {
    conversationManager.setChatVisible(false);
  });
  chatWindow.on("close", (event) => {
    if (isQuitting) {
      return;
    }
    event.preventDefault();
    chatWindow?.hide();
  });
  chatWindow.on("closed", () => {
    chatWindow = null;
  });

  return chatWindow;
}

function createSettingsWindow(): BrowserWindow {
  if (settingsWindow) {
    return settingsWindow;
  }

  settingsWindow = new BrowserWindow({
    width: 440,
    height: 620,
    minWidth: 420,
    minHeight: 560,
    show: false,
    title: "Desktop Pet Settings",
    autoHideMenuBar: true,
    webPreferences: {
      preload: preloadPath,
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  settingsWindow.loadFile(buildWindowUrl("settings.html"));
  settingsWindow.on("close", (event) => {
    if (isQuitting) {
      return;
    }
    event.preventDefault();
    settingsWindow?.hide();
  });
  settingsWindow.on("closed", () => {
    settingsWindow = null;
  });

  return settingsWindow;
}

function createBubbleWindow(): BrowserWindow {
  if (bubbleWindow) {
    return bubbleWindow;
  }

  bubbleWindow = new BrowserWindow({
    width: 280,
    height: 108,
    show: false,
    frame: false,
    transparent: true,
    resizable: false,
    skipTaskbar: true,
    hasShadow: false,
    alwaysOnTop: true,
    webPreferences: {
      preload: preloadPath,
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  bubbleWindow.loadFile(buildWindowUrl("bubble.html"));
  bubbleWindow.on("close", (event) => {
    if (isQuitting) {
      return;
    }
    event.preventDefault();
    hideBubble();
  });
  bubbleWindow.on("closed", () => {
    bubbleWindow = null;
  });

  return bubbleWindow;
}

function showChatWindow(): void {
  const window = createChatWindow();
  positionChatWindow(window);
  window.show();
  window.focus();
  conversationManager.markChatSeen();
}

function showSettingsWindow(): void {
  const window = createSettingsWindow();
  window.show();
  window.focus();
}

function updateBubblePosition(): void {
  if (!bubbleWindow || !petWindow) {
    return;
  }
  const petBounds = petWindow.getBounds();
  const bubbleBounds = bubbleWindow.getBounds();
  bubbleWindow.setBounds({
    ...bubbleBounds,
    x: petBounds.x - bubbleBounds.width + 80,
    y: petBounds.y + 18,
  });
}

function hideBubble(): void {
  if (bubbleTimer) {
    clearTimeout(bubbleTimer);
    bubbleTimer = null;
  }
  activeBubbleKey = "";
  conversationManager.dismissBubble();
  bubbleWindow?.hide();
}

function showBubble(snapshot: ConversationSnapshot): void {
  if (!snapshot.bubble.visible || !snapshot.bubble.message) {
    bubbleWindow?.hide();
    return;
  }

  const window = createBubbleWindow();
  const nextBubbleKey = `${snapshot.bubble.autoTrigger}:${snapshot.bubble.message}`;
  const shouldRefresh =
    activeBubbleKey !== nextBubbleKey || !window.isVisible();

  activeBubbleKey = nextBubbleKey;
  updateBubblePosition();
  if (shouldRefresh) {
    window.showInactive();
    if (bubbleTimer) {
      clearTimeout(bubbleTimer);
    }
    bubbleTimer = setTimeout(() => {
      hideBubble();
    }, 7800);
  }
}

function updateTrayMenu(): void {
  if (!tray) {
    return;
  }

  const contextMenu = Menu.buildFromTemplate([
    {
      label: "Open Chat",
      click: () => showChatWindow(),
    },
    {
      label: !petWindow || !petWindow.isVisible() ? "Show Pet" : "Hide Pet",
      click: () => {
        if (!petWindow) {
          createPetWindow();
          return;
        }
        if (petWindow.isVisible()) {
          petWindow.hide();
        } else {
          petWindow.showInactive();
        }
      },
    },
    {
      label: "Settings",
      click: () => showSettingsWindow(),
    },
    { type: "separator" },
    {
      label: "Quit",
      click: () => {
        isQuitting = true;
        app.quit();
      },
    },
  ]);

  tray.setContextMenu(contextMenu);
}

function broadcastSnapshot(snapshot: ConversationSnapshot): void {
  for (const window of [petWindow, chatWindow, settingsWindow, bubbleWindow]) {
    if (window && !window.isDestroyed()) {
      window.webContents.send("conversation:snapshot", snapshot);
    }
  }

  if (tray) {
    const suffix = snapshot.unreadCount > 0 ? ` (${snapshot.unreadCount})` : "";
    tray.setToolTip(`Life Assistant Pet${suffix}`);
  }

  if (snapshot.bubble.visible) {
    showBubble(snapshot);
  } else {
    activeBubbleKey = "";
    if (bubbleTimer) {
      clearTimeout(bubbleTimer);
      bubbleTimer = null;
    }
    bubbleWindow?.hide();
  }
}

async function updateSettings(nextPartial: Partial<PetSettings>): Promise<PetSettings> {
  const nextSettings = normalizeSettings({
    ...settings,
    ...nextPartial,
  });

  const previousScale = settings.petScale;
  settings = nextSettings;
  backendClient.setBaseUrl(settings.backendUrl);
  applyActivationPolicy();
  applyLoginItemSettings();

  if (petWindow) {
    petWindow.setAlwaysOnTop(settings.alwaysOnTop);
    if (previousScale !== settings.petScale || nextPartial.petPosition) {
      const { width, height } = getPetSize(settings.petScale);
      const position = getPetPosition();
      petWindow.setBounds({
        x: position.x,
        y: position.y,
        width,
        height,
      });
    }
  }

  await persistSettings();
  updateTrayMenu();

  for (const window of [petWindow, chatWindow, settingsWindow, bubbleWindow]) {
    if (window && !window.isDestroyed()) {
      window.webContents.send("settings:updated", settings);
    }
  }

  updateBubblePosition();
  return settings;
}

async function bootstrap(): Promise<void> {
  settingsStore = new SettingsStore(getSettingsFilePath());
  settings = await settingsStore.load();

  backendClient = new BackendClient(settings.backendUrl);
  conversationManager = new ConversationManager(
    backendClient,
    settings.primaryConversationId,
  );

  if (!settings.primaryConversationId) {
    settings.primaryConversationId = conversationManager.getConversationId();
    await persistSettings();
  }

  applyActivationPolicy();
  applyLoginItemSettings();

  await conversationManager.initialize();

  createPetWindow();
  tray = new Tray(createPetTrayIcon(process.platform === "darwin"));
  tray.on("click", () => {
    showChatWindow();
  });
  updateTrayMenu();

  conversationManager.onSnapshot((snapshot) => {
    broadcastSnapshot(snapshot);
  });

  registerIpcHandlers();
}

function registerIpcHandlers(): void {
  ipcMain.handle("desktop:get-environment", async () => getEnvironment());
  ipcMain.handle("conversation:get-snapshot", async () =>
    conversationManager.getSnapshot(),
  );
  ipcMain.handle("conversation:send-message", async (_event, content: string) => {
    await conversationManager.sendUserMessage(content);
  });
  ipcMain.handle("conversation:abort", async () => {
    conversationManager.abort();
  });
  ipcMain.handle("conversation:mark-seen", async () => {
    conversationManager.markChatSeen();
  });
  ipcMain.handle("window:open-chat", async () => {
    showChatWindow();
  });
  ipcMain.handle("window:open-settings", async () => {
    showSettingsWindow();
  });
  ipcMain.handle("bubble:dismiss", async () => {
    hideBubble();
  });
  ipcMain.handle("settings:get", async () => settings);
  ipcMain.handle("settings:update", async (_event, next: Partial<PetSettings>) =>
    updateSettings(next),
  );
  ipcMain.handle("avatar:resolve", async (_event, asset?: string) =>
    resolveAvatarAssetUrl(distRoot, asset ?? settings.avatarAsset),
  );
  ipcMain.handle("pet:click", async () => {
    showChatWindow();
  });
  ipcMain.handle("pet:drag-begin", async (_event, payload: WindowPoint) => {
    if (!petWindow) {
      return;
    }
    const bounds = petWindow.getBounds();
    dragOrigin = {
      cursor: payload,
      window: { x: bounds.x, y: bounds.y },
    };
  });
  ipcMain.handle("pet:drag-update", async (_event, payload: WindowPoint) => {
    if (!petWindow || !dragOrigin) {
      return;
    }
    const { width, height } = petWindow.getBounds();
    const targetPoint = clampToWorkArea(
      {
        x: dragOrigin.window.x + (payload.x - dragOrigin.cursor.x),
        y: dragOrigin.window.y + (payload.y - dragOrigin.cursor.y),
      },
      width,
      height,
    );
    petWindow.setBounds({
      x: targetPoint.x,
      y: targetPoint.y,
      width,
      height,
    });
    updateBubblePosition();
  });
  ipcMain.handle("pet:drag-end", async (_event, payload: WindowPoint) => {
    if (!petWindow) {
      dragOrigin = null;
      return;
    }
    const bounds = petWindow.getBounds();
    dragOrigin = null;
    await updateSettings({
      petPosition: { x: bounds.x, y: bounds.y },
    });
  });
}

app.whenReady().then(async () => {
  await bootstrap();
});

app.on("activate", () => {
  createPetWindow().showInactive();
  showChatWindow();
});

app.on("window-all-closed", () => {
  // Keep the app alive through the desktop pet and tray/menu bar.
});

app.on("before-quit", () => {
  isQuitting = true;
  conversationManager.shutdown();
});
