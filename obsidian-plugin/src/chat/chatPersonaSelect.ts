import { Notice } from "obsidian";

import type {
  AgentClient,
  PersonaState,
  PersonaSummary,
} from "../api/client";
import { createDefaultPersonaState } from "../api/client";
import type { ChatCleanup, ChatPersonaController, ChatViewState } from "./chatTypes";

type PersonaOption =
  | { kind: "auto"; id: "auto"; label: string }
  | { kind: "none"; id: "none"; label: string }
  | { kind: "manual"; id: string; label: string };

export function mountPersonaSelect(
  parentEl: HTMLDivElement,
  client: AgentClient,
  state: ChatViewState,
): ChatPersonaController & { destroy: ChatCleanup } {
  const customSelect = parentEl.createDiv({ cls: "chat-custom-select" });
  customSelect.addClass("chat-persona-select");

  const triggerBtn = customSelect.createDiv({ cls: "custom-select-trigger" });
  triggerBtn.innerHTML = `<span>Persona</span>
      <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m6 9 6 6 6-6"/></svg>
    `;

  const dropdownList = customSelect.createDiv({
    cls: "custom-select-dropdown",
  });

  let personas: PersonaSummary[] = [];
  let options: PersonaOption[] = [];

  const buildOptions = () => {
    options = [
      { kind: "auto", id: "auto", label: "Auto" },
      { kind: "none", id: "none", label: "No Persona" },
      ...personas.map((persona) => ({
        kind: "manual" as const,
        id: persona.id,
        label: persona.title,
      })),
    ];
  };

  const getPersonaTitle = (personaId: string | null): string | null => {
    if (!personaId) {
      return null;
    }
    return personas.find((persona) => persona.id === personaId)?.title ?? personaId;
  };

  const getOptionKey = (personaState: PersonaState): string => {
    if (personaState.mode === "none") {
      return "none";
    }
    if (personaState.mode === "manual") {
      return personaState.manual_persona_id ?? "manual";
    }
    return "auto";
  };

  const getTriggerText = (personaState: PersonaState): string => {
    if (personaState.mode === "none") {
      return "No Persona";
    }
    if (personaState.mode === "manual") {
      return getPersonaTitle(personaState.manual_persona_id) ?? "Manual";
    }
    const routedTitle = getPersonaTitle(personaState.active_persona_id);
    return routedTitle ? `Auto / ${routedTitle}` : "Auto";
  };

  const updateSelectionUi = () => {
    triggerBtn.querySelector("span")?.setText(getTriggerText(state.personaState));
    const selectedKey = getOptionKey(state.personaState);
    Array.from(dropdownList.children).forEach((child) => {
      const optionEl = child as HTMLDivElement;
      optionEl.classList.toggle(
        "selected",
        optionEl.dataset.optionKey === selectedKey,
      );
    });
  };

  const setPersonaState = (nextState: PersonaState) => {
    state.personaState = {
      ...createDefaultPersonaState(),
      ...nextState,
    };
    updateSelectionUi();
  };

  const toState = (option: PersonaOption): PersonaState => {
    if (option.kind === "none") {
      return {
        mode: "none",
        manual_persona_id: null,
        active_persona_id: null,
        source: "none",
        status: "disabled",
      };
    }
    if (option.kind === "manual") {
      return {
        mode: "manual",
        manual_persona_id: option.id,
        active_persona_id: option.id,
        source: "manual",
        status: "manual",
      };
    }
    return createDefaultPersonaState();
  };

  const renderOptions = () => {
    dropdownList.empty();
    buildOptions();

    for (const option of options) {
      const optionEl = dropdownList.createDiv({ cls: "custom-select-option" });
      optionEl.dataset.optionKey = option.kind === "manual" ? option.id : option.kind;
      const nameSpan = optionEl.createEl("span", { cls: "cso-name" });
      nameSpan.setText(option.label);

      const metaSpan = optionEl.createEl("span", { cls: "cso-provider cso-meta" });
      metaSpan.setText(
        option.kind === "auto" ? "AUTO" : option.kind === "none" ? "OFF" : "MANUAL",
      );

      optionEl.addEventListener("click", async (evt: Event) => {
        evt.stopPropagation();
        customSelect.classList.remove("open");

        const previousState = state.personaState;
        const nextState = toState(option);
        setPersonaState(nextState);

        const sessionId = client.sessionId;
        if (!sessionId) {
          return;
        }

        try {
          const updated = await client.patchSession(sessionId, {
            persona_mode: nextState.mode,
            manual_persona_id: nextState.manual_persona_id,
          });
          setPersonaState(updated.persona_state);
        } catch (error) {
          setPersonaState(previousState);
          const message = error instanceof Error ? error.message : String(error);
          new Notice(`Persona switch failed: ${message}`);
        }
      });
    }

    updateSelectionUi();
  };

  void client
    .listPersonas()
    .then((loaded) => {
      personas = loaded;
      renderOptions();
    })
    .catch((error) => {
      console.warn("[ChatView] listPersonas failed:", error);
      renderOptions();
    });

  renderOptions();

  triggerBtn.addEventListener("click", (evt) => {
    evt.stopPropagation();
    evt.preventDefault();
    customSelect.classList.toggle("open");
  });

  const outsideClickListener = (evt: MouseEvent) => {
    if (!customSelect.contains(evt.target as Node)) {
      customSelect.classList.remove("open");
    }
  };

  document.addEventListener("click", outsideClickListener);

  return {
    setPersonaState,
    destroy: () => {
      document.removeEventListener("click", outsideClickListener);
    },
  };
}
