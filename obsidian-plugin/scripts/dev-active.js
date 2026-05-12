const fs = require("fs");
const path = require("path");

const esbuild = require("esbuild");

const { resolveVaultForDeploy } = require("./obsidianVault");

const sourceDir = path.resolve(__dirname, "..");
const repoRoot = path.resolve(sourceDir, "..");
const staticFiles = ["manifest.json", "styles.css"];
const watchedStaticFiles = [];

let buildCount = 0;
let shuttingDown = false;
let deployQueue = Promise.resolve();
let lastAnnouncedTarget = null;
let vaultPoller = null;

function getPluginTarget() {
  const resolvedVault = resolveVaultForDeploy();
  const pluginDir = path.join(
    resolvedVault.vaultPath,
    ".obsidian",
    "plugins",
    "crabby",
  );
  return {
    ...resolvedVault,
    pluginDir,
  };
}

function ensurePluginDir(target) {
  if (!fs.existsSync(target.pluginDir)) {
    fs.mkdirSync(target.pluginDir, { recursive: true });
    console.log(`[deploy] Created ${target.pluginDir}`);
  }
}

function listArtifactFiles() {
  return ["main.js", ...staticFiles].filter((file) =>
    fs.existsSync(path.join(sourceDir, file)),
  );
}

function resolveDevPythonPath() {
  const candidates =
    process.platform === "win32"
      ? [
          path.join(repoRoot, "server", ".venv", "Scripts", "python.exe"),
          path.join(repoRoot, "server", ".venv", "Scripts", "pythonw.exe"),
        ]
      : [
          path.join(repoRoot, "server", ".venv", "bin", "python"),
          path.join(repoRoot, "server", ".venv", "bin", "python3"),
        ];

  return candidates.find((candidate) => fs.existsSync(candidate)) || "python";
}

async function writeDevRuntimeConfig(target) {
  const configPath = path.join(target.pluginDir, ".dev-runtime.json");
  const config = {
    mode: "dev",
    repoRoot,
    backendCommand: resolveDevPythonPath(),
    backendArgs: ["-m", "uvicorn", "main:app", "--reload"],
    backendCwd: path.join(repoRoot, "server"),
  };
  await fs.promises.writeFile(configPath, `${JSON.stringify(config, null, 2)}\n`, "utf8");
  console.log(`[deploy] Synced .dev-runtime.json`);
}

function announceTargetIfChanged(target) {
  if (target.pluginDir === lastAnnouncedTarget?.pluginDir) {
    return;
  }

  if (lastAnnouncedTarget) {
    console.log(
      `[vault] Sync target switched: ${lastAnnouncedTarget.vaultPath} -> ${target.vaultPath}`,
    );
  } else {
    console.log(`[vault] Active vault: ${target.vaultPath}`);
  }
  console.log(`[deploy] ${target.detail}`);
  lastAnnouncedTarget = target;
}

function pollActiveVaultTarget() {
  try {
    announceTargetIfChanged(getPluginTarget());
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    console.error(`[vault] Failed to resolve active vault: ${message}`);
  }
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function copyFileWithRetries(src, dest) {
  const maxWaitMs = 15000;
  const startedAt = Date.now();
  let attempt = 0;
  while (true) {
    attempt += 1;
    try {
      await fs.promises.copyFile(src, dest);
      return;
    } catch (error) {
      const code = error && typeof error === "object" ? error.code : "";
      const retryable =
        code === "EPERM" || code === "EACCES" || code === "EBUSY";
      const elapsedMs = Date.now() - startedAt;
      if (!retryable || elapsedMs >= maxWaitMs) {
        throw error;
      }
      const delayMs = Math.min(250 * attempt, 1000);
      await sleep(delayMs);
    }
  }
}

async function copyArtifacts(reason) {
  const target = getPluginTarget();
  ensurePluginDir(target);
  announceTargetIfChanged(target);

  for (const file of listArtifactFiles()) {
    const src = path.join(sourceDir, file);
    const dest = path.join(target.pluginDir, file);
    try {
      await copyFileWithRetries(src, dest);
      console.log(`[deploy] Synced ${file} (${reason})`);
    } catch (error) {
      const message =
        error instanceof Error ? error.message : String(error);
      console.error(`[deploy] Failed to sync ${file}: ${message}`);
    }
  }
  await writeDevRuntimeConfig(target);
}

function scheduleCopy(reason) {
  deployQueue = deployQueue
    .then(() => copyArtifacts(reason))
    .catch((error) => {
      const message = error instanceof Error ? error.message : String(error);
      console.error(`[deploy] Unexpected deploy error: ${message}`);
    });
  return deployQueue;
}

function watchStaticFile(file) {
  const fullPath = path.join(sourceDir, file);
  if (!fs.existsSync(fullPath)) {
    return;
  }

  fs.watchFile(fullPath, { interval: 300 }, (current, previous) => {
    if (current.mtimeMs === previous.mtimeMs) {
      return;
    }
    void scheduleCopy(`${file} updated`);
  });
  watchedStaticFiles.push(fullPath);
}

async function main() {
  for (const file of staticFiles) {
    watchStaticFile(file);
  }
  pollActiveVaultTarget();
  vaultPoller = setInterval(pollActiveVaultTarget, 1500);

  const ctx = await esbuild.context({
    entryPoints: [path.join(sourceDir, "src", "main.ts")],
    outfile: path.join(sourceDir, "main.js"),
    bundle: true,
    format: "cjs",
    platform: "node",
    external: ["obsidian"],
    sourcemap: true,
    plugins: [
      {
        name: "deploy-to-active-vault",
        setup(build) {
          build.onEnd(async (result) => {
            if (result.errors.length > 0) {
              console.error(
                `[build] Failed with ${result.errors.length} error(s); skipped deploy.`,
              );
              return;
            }

            buildCount += 1;
            console.log(`[build] Build #${buildCount} succeeded.`);
            await scheduleCopy(`build #${buildCount}`);
          });
        },
      },
    ],
  });

  const shutdown = async (signal) => {
    if (shuttingDown) {
      return;
    }
    shuttingDown = true;
    console.log(`\n[dev:active] Stopping (${signal})...`);
    for (const file of watchedStaticFiles) {
      fs.unwatchFile(file);
    }
    if (vaultPoller) {
      clearInterval(vaultPoller);
      vaultPoller = null;
    }
    await ctx.dispose();
    process.exit(0);
  };

  process.on("SIGINT", () => {
    void shutdown("SIGINT");
  });
  process.on("SIGTERM", () => {
    void shutdown("SIGTERM");
  });

  await ctx.watch();
  console.log("[dev:active] Watching src/main.ts and deploy artifacts.");
  console.log("[dev:active] Press Ctrl+C to stop.");
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
