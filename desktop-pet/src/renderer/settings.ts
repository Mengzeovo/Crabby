import {
  CLASSIC_AVATAR_ASSET,
  DEFAULT_AVATAR_ASSET,
} from "../shared/constants";
import type { PetSettings } from "../shared/types";

const form = document.getElementById("settingsForm") as HTMLFormElement;
const backendUrlInput = document.getElementById("backendUrl") as HTMLInputElement;
const avatarAssetInput = document.getElementById("avatarAsset") as HTMLInputElement;
const petScaleInput = document.getElementById("petScale") as HTMLInputElement;
const scaleLabel = document.getElementById("scaleLabel") as HTMLElement;
const alwaysOnTopInput = document.getElementById("alwaysOnTop") as HTMLInputElement;
const launchOnLoginInput = document.getElementById("launchOnLogin") as HTMLInputElement;
const showDockIconField = document.getElementById("showDockField") as HTMLLabelElement;
const showDockIconInput = document.getElementById("showDockIcon") as HTMLInputElement;
const avatarPreview = document.getElementById("avatarPreview") as HTMLImageElement;
const avatarLabel = document.getElementById("avatarLabel") as HTMLSpanElement;
const statusText = document.getElementById("statusText") as HTMLParagraphElement;
const crabbyButton = document.getElementById("crabbyAvatar") as HTMLButtonElement;
const legacyButton = document.getElementById("legacyAvatar") as HTMLButtonElement;

function syncScaleLabel(value: string): void {
  scaleLabel.textContent = `${Number(value).toFixed(2)}x`;
}

async function updatePreview(asset: string): Promise<void> {
  avatarPreview.src = await window.desktopPet.resolveAvatarUrl(asset);
  avatarLabel.textContent = asset;
}

async function renderSettings(settings: PetSettings): Promise<void> {
  backendUrlInput.value = settings.backendUrl;
  avatarAssetInput.value = settings.avatarAsset;
  petScaleInput.value = String(settings.petScale);
  syncScaleLabel(String(settings.petScale));
  alwaysOnTopInput.checked = settings.alwaysOnTop;
  launchOnLoginInput.checked = settings.launchOnLogin;
  showDockIconInput.checked = settings.showDockIcon;
  await updatePreview(settings.avatarAsset);
}

petScaleInput.addEventListener("input", () => {
  syncScaleLabel(petScaleInput.value);
});

avatarAssetInput.addEventListener("input", () => {
  statusText.textContent = "";
  void updatePreview(avatarAssetInput.value.trim() || DEFAULT_AVATAR_ASSET);
});

crabbyButton.addEventListener("click", () => {
  avatarAssetInput.value = DEFAULT_AVATAR_ASSET;
  void updatePreview(DEFAULT_AVATAR_ASSET);
});

legacyButton.addEventListener("click", () => {
  avatarAssetInput.value = CLASSIC_AVATAR_ASSET;
  void updatePreview(CLASSIC_AVATAR_ASSET);
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  statusText.textContent = "Saving...";
  const nextSettings = await window.desktopPet.updateSettings({
    backendUrl: backendUrlInput.value.trim(),
    avatarAsset: avatarAssetInput.value.trim() || DEFAULT_AVATAR_ASSET,
    petScale: Number(petScaleInput.value),
    alwaysOnTop: alwaysOnTopInput.checked,
    launchOnLogin: launchOnLoginInput.checked,
    showDockIcon: showDockIconInput.checked,
  });
  await renderSettings(nextSettings);
  statusText.textContent = "Saved. Changes are live.";
});

window.desktopPet.subscribeSettings((settings) => {
  void renderSettings(settings);
});

void (async () => {
  const environment = await window.desktopPet.getEnvironment();
  showDockIconField.hidden = !environment.isMac;
  await renderSettings(await window.desktopPet.getSettings());
})();
