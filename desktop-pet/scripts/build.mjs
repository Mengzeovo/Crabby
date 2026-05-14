import { mkdir, copyFile, readdir, rm, stat } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

import esbuild from "esbuild";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const rootDir = path.resolve(__dirname, "..");
const srcDir = path.join(rootDir, "src");
const distDir = path.join(rootDir, "dist");

async function ensureCleanDist() {
  await rm(distDir, { recursive: true, force: true });
  await mkdir(distDir, { recursive: true });
}

async function copyRecursive(sourceDir, targetDir) {
  await mkdir(targetDir, { recursive: true });
  const entries = await readdir(sourceDir);
  await Promise.all(
    entries.map(async (entry) => {
      const sourcePath = path.join(sourceDir, entry);
      const targetPath = path.join(targetDir, entry);
      const entryStat = await stat(sourcePath);
      if (entryStat.isDirectory()) {
        await copyRecursive(sourcePath, targetPath);
        return;
      }
      await copyFile(sourcePath, targetPath);
    }),
  );
}

async function copyRecursiveIfExists(sourceDir, targetDir) {
  try {
    const sourceStat = await stat(sourceDir);
    if (!sourceStat.isDirectory()) {
      return;
    }
  } catch {
    return;
  }

  await copyRecursive(sourceDir, targetDir);
}

async function copyRendererStatics() {
  const rendererDist = path.join(distDir, "renderer");
  await mkdir(rendererDist, { recursive: true });

  for (const entry of await readdir(path.join(srcDir, "renderer"))) {
    if (!entry.endsWith(".html")) {
      continue;
    }
    await copyFile(
      path.join(srcDir, "renderer", entry),
      path.join(rendererDist, entry),
    );
  }

  await copyRecursive(
    path.join(srcDir, "renderer", "styles"),
    path.join(rendererDist, "styles"),
  );
}

async function build() {
  await ensureCleanDist();

  await esbuild.build({
    entryPoints: {
      index: path.join(srcDir, "main", "index.ts"),
      preload: path.join(srcDir, "main", "preload.ts"),
    },
    outdir: path.join(distDir, "main"),
    bundle: true,
    format: "cjs",
    platform: "node",
    target: ["node22"],
    sourcemap: true,
    external: ["electron"],
    outExtension: {
      ".js": ".cjs",
    },
  });

  await esbuild.build({
    entryPoints: {
      pet: path.join(srcDir, "renderer", "pet.ts"),
      chat: path.join(srcDir, "renderer", "chat.ts"),
      settings: path.join(srcDir, "renderer", "settings.ts"),
      bubble: path.join(srcDir, "renderer", "bubble.ts"),
    },
    outdir: path.join(distDir, "renderer"),
    bundle: true,
    format: "iife",
    platform: "browser",
    target: ["chrome122"],
    sourcemap: true,
  });

  await copyRendererStatics();
  await copyRecursiveIfExists(path.join(srcDir, "assets"), path.join(distDir, "assets"));
  await copyRecursiveIfExists(path.join(rootDir, "assets"), path.join(distDir, "assets"));
}

build().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
