/**
 * Crabby - Obsidian plugin entry point.
 */

import { Notice, Plugin } from "obsidian";

import { AgentClient } from "./api/client";
import { ChatView, VIEW_TYPE_CHAT } from "./chat/ChatView";
import { ObsidianClientToolBridge } from "./clientTools/obsidianClientTools";
import {
  activateLlmProfileOnBackend,
  fetchLlmProfilesFromBackend,
  saveLlmProfileToBackend,
  syncVaultPathLocally,
} from "./config/backendConfig";
import {
  hydrateSettings,
  needsBackendEnvPathMigration,
} from "./config/settingsData";
import { notifySettingsUpdated } from "./config/settingsEvents";
import {
  DEFAULT_SETTINGS,
  CrabbySettings,
  CrabbySettingTab,
  isDraftLlmProfile,
} from "./settings";
import { BackendRuntimeManager } from "./runtime/backendRuntime";
import { SearchIndex } from "./search/searchIndex";

const PLUGIN_VERSION = "0.3.0";

export default class CrabbyPlugin extends Plugin {
  settings: CrabbySettings = hydrateSettings(DEFAULT_SETTINGS, null);
  runtimeManager: BackendRuntimeManager | null = null;
  clientToolBridge: ObsidianClientToolBridge | null = null;
  searchIndex: SearchIndex | null = null;
  private unloaded = false;

  async onload(): Promise<void> {
    this.unloaded = false;
    await this.loadSettings();
    this.runtimeManager = new BackendRuntimeManager(this.app, this.settings);
    this.clientToolBridge = new ObsidianClientToolBridge(
      this,
      () => this.settings.backendUrl,
    );
    this.clientToolBridge.start();

    this.searchIndex = new SearchIndex(this.app, {
      pluginVersion: PLUGIN_VERSION,
    });
    this.app.workspace.onLayoutReady(() => {
      void this.initializeSearchIndex();
    });

    this.registerView(VIEW_TYPE_CHAT, (leaf) => new ChatView(leaf, this));
    this.addSettingTab(new CrabbySettingTab(this.app, this));

    this.addRibbonIcon("bot", "Crabby", () => {
      this.activateView();
    });

    this.addCommand({
      id: "open-chat",
      name: "Open Crabby Chat",
      callback: () => this.activateView(),
    });

    this.startRuntimeInBackground();
  }

  async onunload(): Promise<void> {
    this.unloaded = true;
    this.app.workspace.detachLeavesOfType(VIEW_TYPE_CHAT);
    if (this.clientToolBridge) {
      this.clientToolBridge.stop();
      this.clientToolBridge = null;
    }
    if (this.searchIndex) {
      await this.searchIndex.shutdown();
      this.searchIndex = null;
    }
    if (this.runtimeManager) {
      await this.runtimeManager.stop();
      this.runtimeManager = null;
    }
  }

  private async initializeSearchIndex(): Promise<void> {
    const index = this.searchIndex;
    if (!index || this.unloaded) {
      return;
    }
    index.attachVaultEvents();
    try {
      await index.initialize();
      if (this.unloaded || this.searchIndex !== index) {
        return;
      }
    } catch (error) {
      console.warn("[Crabby] SearchIndex initialization failed", error);
    }
  }

  private startRuntimeInBackground(): void {
    const manager = this.runtimeManager;
    if (!manager) {
      return;
    }

    void (async () => {
      try {
        await manager.ensureRuntimeLayout();
        if (this.unloaded || this.runtimeManager !== manager) {
          return;
        }
        const runtimeStatus = await manager.start();
        if (this.unloaded || this.runtimeManager !== manager) {
          return;
        }
        await this.syncLlmProfilesFromBackend({ migrateLocalProfiles: true });
        await this.saveSettings();

        if (!runtimeStatus.running && runtimeStatus.mode === "production") {
          new Notice(
            "Crabby backend runtime is not installed. Open settings to install it.",
          );
        }
      } catch (error) {
        if (!this.unloaded) {
          console.error(
            "[Crabby] Failed to start backend runtime:",
            error,
          );
          const message = error instanceof Error ? error.message : String(error);
          new Notice(`Crabby backend startup failed: ${message}`);
        }
      }
    })();
  }

  async loadSettings(): Promise<void> {
    const loaded = await this.loadData();
    this.settings = hydrateSettings(DEFAULT_SETTINGS, loaded);
    if (needsBackendEnvPathMigration(loaded)) {
      await this.saveSettings();
    }
  }

  async saveSettings(): Promise<void> {
    await this.saveData(this.settings);
    notifySettingsUpdated();
  }

  public restartClientToolBridge(): void {
    if (!this.clientToolBridge) {
      return;
    }
    this.clientToolBridge.stop();
    this.clientToolBridge.start();
  }

  public getCurrentVaultPath(): string {
    return (
      ((this.app.vault.adapter as { basePath?: string }).basePath as string) ?? ""
    ).trim();
  }

  public async ensureBackendVaultPathSynced(
    client?: Pick<AgentClient, "reloadSettings">,
  ): Promise<{ ok: boolean; changed: boolean; message: string }> {
    try {
      const result = await syncVaultPathLocally(
        this.settings,
        this.getCurrentVaultPath(),
        client ?? new AgentClient(this.settings.backendUrl),
      );
      return {
        ok: result.ok,
        changed: Boolean(result.changed),
        message: result.message,
      };
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      console.error("[Crabby] Failed to sync backend vault path:", error);
      return {
        ok: false,
        changed: false,
        message:
          "Failed to sync the current vault path with the backend .env. " +
          "Check the plugin's backend .env path setting. " +
          message,
      };
    }
  }

  public async applyLlmProfile(): Promise<{ ok: boolean; message: string }> {
    const activeProfile =
      this.settings.llmProfiles.find(
        (profile) =>
          profile.id === this.settings.activeProfileId &&
          !isDraftLlmProfile(profile),
      ) ??
      this.settings.llmProfiles.find((profile) => !isDraftLlmProfile(profile));

    if (!activeProfile) {
      return { ok: false, message: "No LLM profile is configured." };
    }

    await this.saveSettings();

    try {
      const client = new AgentClient(this.settings.backendUrl);
      const result = await activateLlmProfileOnBackend(
        this.settings,
        activeProfile.id,
        client,
      );
      if (result.ok) {
        await this.saveSettings();
      }
      return { ok: result.ok, message: result.message };
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      console.error(error);
      return {
        ok: false,
        message: `Failed to apply the active LLM profile: ${message}`,
      };
    }
  }

  public async syncLlmProfilesFromBackend(
    options: { migrateLocalProfiles?: boolean } = {},
  ): Promise<{ ok: boolean; message: string }> {
    const client = new AgentClient(this.settings.backendUrl);
    const localProfiles = this.settings.llmProfiles
      .filter((profile) => !isDraftLlmProfile(profile))
      .map((profile) => ({
        ...profile,
      }));
    const localActiveProfileId = this.settings.activeProfileId;

    const fetched = await fetchLlmProfilesFromBackend(this.settings, client);
    if (!fetched.ok) {
      return { ok: false, message: fetched.message };
    }

    if (
      options.migrateLocalProfiles &&
      fetched.profiles?.length === 0 &&
      localProfiles.length > 0
    ) {
      for (const profile of localProfiles) {
        const activate =
          profile.id === localActiveProfileId ||
          (!localActiveProfileId && profile.id === localProfiles[0].id);
        const saved = await saveLlmProfileToBackend(
          this.settings,
          profile,
          client,
          activate,
        );
        if (!saved.ok) {
          return { ok: false, message: saved.message };
        }
      }
      await this.saveSettings();
      return { ok: true, message: "Migrated local LLM profiles to backend." };
    }

    await this.saveSettings();
    return { ok: true, message: fetched.message };
  }

  private async activateView(): Promise<void> {
    const { workspace } = this.app;

    let leaf = workspace.getLeavesOfType(VIEW_TYPE_CHAT)[0];
    if (!leaf) {
      const rightLeaf = workspace.getRightLeaf(false);
      if (rightLeaf) {
        leaf = rightLeaf;
        await leaf.setViewState({ type: VIEW_TYPE_CHAT, active: true });
      }
    }

    if (leaf) {
      workspace.revealLeaf(leaf);
    }
  }
}
