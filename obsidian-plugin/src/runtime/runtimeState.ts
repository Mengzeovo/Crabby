import { isAbsolute, relative, resolve, sep } from "node:path";

function escapesRuntimeDir(relativePath: string): boolean {
  return relativePath === ".." || relativePath.startsWith(`..${sep}`);
}

export function serializeRuntimeExecutablePath(
  runtimeDir: string,
  executablePath: string,
): string {
  const resolvedRuntimeDir = resolve(runtimeDir);
  const resolvedExecutablePath = resolve(resolvedRuntimeDir, executablePath);
  const relativePath = relative(resolvedRuntimeDir, resolvedExecutablePath);

  if (!relativePath || isAbsolute(relativePath) || escapesRuntimeDir(relativePath)) {
    return resolvedExecutablePath;
  }

  return relativePath;
}

export function resolveRuntimeExecutablePath(
  runtimeDir: string,
  executablePath?: string | null,
): string | null {
  const trimmed = executablePath?.trim();
  if (!trimmed) {
    return null;
  }

  const resolvedRuntimeDir = resolve(runtimeDir);
  const resolvedExecutablePath = resolve(resolvedRuntimeDir, trimmed);
  if (isAbsolute(trimmed)) {
    return resolvedExecutablePath;
  }

  const relativePath = relative(resolvedRuntimeDir, resolvedExecutablePath);
  if (!relativePath || isAbsolute(relativePath) || escapesRuntimeDir(relativePath)) {
    return null;
  }

  return resolvedExecutablePath;
}
