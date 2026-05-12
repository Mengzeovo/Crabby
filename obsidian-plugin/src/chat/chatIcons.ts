export const ICON_SEND = `
    <svg viewBox="0 0 24 24" width="15" height="15" fill="none"
      stroke="currentColor" stroke-width="2.5"
      stroke-linecap="round" stroke-linejoin="round">
      <line x1="12" y1="19" x2="12" y2="5"/>
      <polyline points="5 12 12 5 19 12"/>
    </svg>`;

export const ICON_STOP = `
    <svg viewBox="0 0 24 24" width="13" height="13" fill="currentColor">
      <rect x="4" y="4" width="16" height="16" rx="3"/>
    </svg>`;

export const ICON_HISTORY = `
    <svg viewBox="0 0 24 24" width="16" height="16" fill="none"
      stroke="currentColor" stroke-width="2"
      stroke-linecap="round" stroke-linejoin="round">
      <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/>
      <path d="M3 3v5h5"/>
      <path d="M12 7v5l4 2"/>
    </svg>`;

export const ICON_PLUS = `
    <svg viewBox="0 0 24 24" width="16" height="16" fill="none"
      stroke="currentColor" stroke-width="2.5"
      stroke-linecap="round" stroke-linejoin="round">
      <line x1="12" y1="5" x2="12" y2="19"/>
      <line x1="5" y1="12" x2="19" y2="12"/>
    </svg>`;

export const ICON_TREE = `
    <svg viewBox="0 0 24 24" width="16" height="16" fill="none"
      stroke="currentColor" stroke-width="2"
      stroke-linecap="round" stroke-linejoin="round">
      <path d="M12 3v5"/>
      <path d="M6 13v3"/>
      <path d="M18 13v3"/>
      <path d="M6 21v-2"/>
      <path d="M18 21v-2"/>
      <path d="M12 8H6a2 2 0 0 0-2 2v3"/>
      <path d="M12 8h6a2 2 0 0 1 2 2v3"/>
      <circle cx="12" cy="3" r="2"/>
      <circle cx="6" cy="16" r="2"/>
      <circle cx="18" cy="16" r="2"/>
    </svg>`;

export const ICON_FORK = `
    <svg viewBox="0 0 24 24" width="14" height="14" fill="none"
      stroke="currentColor" stroke-width="2"
      stroke-linecap="round" stroke-linejoin="round">
      <circle cx="6" cy="18" r="3"/>
      <circle cx="6" cy="6" r="3"/>
      <circle cx="18" cy="6" r="3"/>
      <path d="M6 9v6"/>
      <path d="M9 6h3a6 6 0 0 1 6 6v3"/>
    </svg>`;

export const ICON_ATTACH = `
    <svg viewBox="0 0 24 24" width="15" height="15" fill="none"
      stroke="currentColor" stroke-width="2"
      stroke-linecap="round" stroke-linejoin="round">
      <path d="M21.44 11.05l-8.49 8.49a6 6 0 1 1-8.49-8.49l9.19-9.19a4 4 0 1 1 5.66 5.66L9.41 17.41a2 2 0 1 1-2.83-2.83l8.49-8.48"/>
    </svg>`;

export const ICON_TRASH = `
    <svg viewBox="0 0 24 24" width="14" height="14" fill="none"
      stroke="currentColor" stroke-width="2"
      stroke-linecap="round" stroke-linejoin="round">
      <polyline points="3 6 5 6 21 6"/>
      <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
    </svg>`;

export function getToolIcon(name: string): string {
  const normalized = name.toLowerCase();
  if (
    normalized === "bash" ||
    normalized === "shell" ||
    normalized === "run_command"
  ) {
    return ">_";
  }
  if (normalized.includes("read") || normalized.includes("file")) {
    return "\ud83d\udcc4";
  }
  if (normalized.includes("write")) {
    return "\u270f\ufe0f";
  }
  if (normalized.includes("search") || normalized.includes("grep")) {
    return "\ud83d\udd0d";
  }
  if (normalized.includes("mempalace") || normalized.includes("memory")) {
    return "\ud83e\udde0";
  }
  if (normalized.includes("browser") || normalized.includes("web")) {
    return "\ud83c\udf10";
  }
  return "\ud83d\udd27";
}
