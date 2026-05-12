import { Notice } from "obsidian";

import type { AgentClient } from "../api/client";
import { activateLlmProfileOnBackend } from "../config/backendConfig";
import { getLlmProviderPreset } from "../config/llmProviders";
import { SETTINGS_UPDATED_EVENT } from "../config/settingsEvents";
import type CrabbyPlugin from "../main";
import type { LlmProfile } from "../settings";
import type { ChatCleanup } from "./chatTypes";

type ProfileOption = {
  profileId: string;
  optionEl: HTMLDivElement;
};

function getProfileDisplayName(profile: LlmProfile): string {
  return (
    profile.name.trim() ||
    profile.model.trim() ||
    getLlmProviderPreset(profile.provider).label
  );
}

function getProviderBadgeText(profile: LlmProfile): string {
  return getLlmProviderPreset(profile.provider).label.toUpperCase();
}

export function mountProfileSelect(
  parentEl: HTMLDivElement,
  plugin: CrabbyPlugin,
  client: AgentClient,
): ChatCleanup {
  const customSelect = parentEl.createDiv({ cls: "chat-custom-select" });

  const triggerBtn = customSelect.createDiv({ cls: "custom-select-trigger" });
  triggerBtn.innerHTML = `<span>Select Model</span>
      <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m6 9 6 6 6-6"/></svg>
    `;

  const dropdownList = customSelect.createDiv({
    cls: "custom-select-dropdown",
  });
  let optionEls: ProfileOption[] = [];

  const getDisplayedProfile = () =>
    plugin.settings.llmProfiles.find(
      (profile) => profile.id === plugin.settings.activeProfileId,
    ) ?? plugin.settings.llmProfiles[0];

  const refreshSelectionUi = () => {
    const activeProfile = getDisplayedProfile();
    triggerBtn
      .querySelector("span")
      ?.setText(
        activeProfile ? getProfileDisplayName(activeProfile) : "Select Model",
      );

    optionEls.forEach(({ optionEl, profileId }) => {
      optionEl.classList.toggle(
        "selected",
        profileId === plugin.settings.activeProfileId,
      );
    });
  };

  const renderOptions = () => {
    dropdownList.empty();
    optionEls = [];

    if (plugin.settings.llmProfiles.length === 0) {
      const emptyEl = dropdownList.createDiv({
        cls: "custom-select-option custom-select-option-empty",
      });
      emptyEl.setText("No LLM profiles");
      refreshSelectionUi();
      return;
    }

    plugin.settings.llmProfiles.forEach((profile) => {
      const optionEl = dropdownList.createDiv({ cls: "custom-select-option" });
      optionEls.push({ profileId: profile.id, optionEl });

      const labelWrap = optionEl.createDiv({ cls: "cso-label" });
      const nameSpan = labelWrap.createEl("span", { cls: "cso-name" });
      nameSpan.setText(getProfileDisplayName(profile));

      const modelSpan = labelWrap.createEl("span", { cls: "cso-model" });
      modelSpan.setText(
        `${getLlmProviderPreset(profile.provider).label} / ${profile.model}`,
      );

      const providerBadge = optionEl.createEl("span", { cls: "cso-provider" });
      providerBadge.setText(getProviderBadgeText(profile));
      providerBadge.setAttribute("data-provider", profile.provider);

      optionEl.addEventListener("click", async (evt: Event) => {
        evt.stopPropagation();
        customSelect.classList.remove("open");

        const currentProfile =
          plugin.settings.llmProfiles.find((item) => item.id === profile.id) ??
          profile;

        if (currentProfile.id === plugin.settings.activeProfileId) {
          refreshSelectionUi();
          return;
        }

        try {
          const result = await activateLlmProfileOnBackend(
            plugin.settings,
            currentProfile.id,
            client,
          );

          if (result.ok) {
            await plugin.saveSettings();
            renderOptions();
            new Notice(
              `Switched to model: ${getProfileDisplayName(currentProfile)}`,
            );
            return;
          }

          refreshSelectionUi();
          new Notice(`Profile switch failed: ${result.message}`);
        } catch (error) {
          refreshSelectionUi();
          const message = error instanceof Error ? error.message : String(error);
          new Notice(`Profile switch failed: ${message}`);
        }
      });
    });

    refreshSelectionUi();
  };

  renderOptions();

  triggerBtn.addEventListener("click", (evt) => {
    evt.stopPropagation();
    evt.preventDefault();
    renderOptions();
    customSelect.classList.toggle("open");
  });

  const outsideClickListener = (evt: MouseEvent) => {
    if (!customSelect.contains(evt.target as Node)) {
      customSelect.classList.remove("open");
    }
  };

  const settingsUpdatedListener = () => {
    renderOptions();
  };

  document.addEventListener("click", outsideClickListener);
  document.addEventListener(SETTINGS_UPDATED_EVENT, settingsUpdatedListener);

  return () => {
    document.removeEventListener("click", outsideClickListener);
    document.removeEventListener(SETTINGS_UPDATED_EVENT, settingsUpdatedListener);
  };
}
