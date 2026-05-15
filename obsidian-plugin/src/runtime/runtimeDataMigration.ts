import {
  cpSync,
  existsSync,
  mkdirSync,
  readdirSync,
  renameSync,
  rmdirSync,
  statSync,
} from "node:fs";
import { dirname, join } from "node:path";

export type RuntimeDataMigrationStatus =
  | "missing"
  | "moved"
  | "merged"
  | "skipped"
  | "blocked"
  | "failed";

export interface RuntimeDataMigration {
  label: string;
  legacyPath: string;
  targetPath: string;
}

export interface RuntimeDataMigrationResult extends RuntimeDataMigration {
  status: RuntimeDataMigrationStatus;
  movedEntries: number;
  skippedEntries: number;
  message: string;
}

interface MergeCounts {
  movedEntries: number;
  skippedEntries: number;
}

export function migrateRuntimeDataDirectory(
  migration: RuntimeDataMigration,
): RuntimeDataMigrationResult {
  const { legacyPath, targetPath } = migration;
  if (!existsSync(legacyPath)) {
    return result(migration, "missing", 0, 0, "legacy directory is absent");
  }

  try {
    if (!statSync(legacyPath).isDirectory()) {
      return result(migration, "blocked", 0, 1, "legacy path is not a directory");
    }

    if (!existsSync(targetPath)) {
      mkdirSync(dirname(targetPath), { recursive: true });
      moveOrCopyPath(legacyPath, targetPath);
      return result(migration, "moved", 1, 0, "moved legacy directory");
    }

    if (!statSync(targetPath).isDirectory()) {
      return result(migration, "blocked", 0, 1, "target path is not a directory");
    }

    const counts = mergeDirectoryContents(legacyPath, targetPath);
    removeEmptyDirectory(legacyPath);
    if (counts.movedEntries > 0) {
      return result(
        migration,
        "merged",
        counts.movedEntries,
        counts.skippedEntries,
        "merged missing legacy entries into existing directory",
      );
    }

    return result(
      migration,
      counts.skippedEntries > 0 ? "skipped" : "merged",
      counts.movedEntries,
      counts.skippedEntries,
      counts.skippedEntries > 0
        ? "existing target entries were kept"
        : "legacy directory was empty",
    );
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return result(migration, "failed", 0, 1, message);
  }
}

export function migrateRuntimeDataDirectories(
  migrations: RuntimeDataMigration[],
): RuntimeDataMigrationResult[] {
  return migrations.map((migration) => migrateRuntimeDataDirectory(migration));
}

function mergeDirectoryContents(sourceDir: string, targetDir: string): MergeCounts {
  const counts: MergeCounts = {
    movedEntries: 0,
    skippedEntries: 0,
  };

  mkdirSync(targetDir, { recursive: true });

  for (const entry of readdirSync(sourceDir)) {
    const sourcePath = join(sourceDir, entry);
    const targetPath = join(targetDir, entry);

    if (!existsSync(targetPath)) {
      moveOrCopyPath(sourcePath, targetPath);
      counts.movedEntries += 1;
      continue;
    }

    const sourceStats = statSync(sourcePath);
    const targetStats = statSync(targetPath);
    if (sourceStats.isDirectory() && targetStats.isDirectory()) {
      const childCounts = mergeDirectoryContents(sourcePath, targetPath);
      counts.movedEntries += childCounts.movedEntries;
      counts.skippedEntries += childCounts.skippedEntries;
      removeEmptyDirectory(sourcePath);
      continue;
    }

    counts.skippedEntries += 1;
  }

  return counts;
}

function moveOrCopyPath(sourcePath: string, targetPath: string): void {
  try {
    renameSync(sourcePath, targetPath);
  } catch {
    cpSync(sourcePath, targetPath, {
      recursive: true,
      errorOnExist: true,
      force: false,
    });
  }
}

function removeEmptyDirectory(path: string): void {
  try {
    rmdirSync(path);
  } catch {
    // Keep non-empty legacy directories so conflicting files are not lost.
  }
}

function result(
  migration: RuntimeDataMigration,
  status: RuntimeDataMigrationStatus,
  movedEntries: number,
  skippedEntries: number,
  message: string,
): RuntimeDataMigrationResult {
  return {
    ...migration,
    status,
    movedEntries,
    skippedEntries,
    message,
  };
}
