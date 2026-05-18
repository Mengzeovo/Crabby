const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const esbuild = require("esbuild");
const obsidianVault = require("./obsidianVault");

async function loadModule(relativePath, outputName) {
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), "laa-config-module-"));
  const outfile = path.join(tempDir, outputName);

  await esbuild.build({
    entryPoints: [path.join(__dirname, "..", "src", ...relativePath.split("/"))],
    outfile,
    bundle: true,
    platform: "node",
    format: "cjs",
    logLevel: "silent",
  });

  return require(outfile);
}

async function testBackendConfig(mod) {
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), "laa-env-test-"));
  const envPath = path.join(tempDir, ".env");

  const unresolved = mod.resolveBackendEnvPath({
    backendEnvPath: "",
    backendPath: path.join(tempDir, "server"),
  });
  assert.equal(unresolved.ok, false);
  assert.equal(unresolved.derivedFromLegacyPath, false);
  assert.equal(unresolved.envPath, undefined);
  assert.equal(
    mod.getBackendEnvPathInputValue({
      backendEnvPath: "",
      backendPath: path.join(tempDir, "server"),
    }),
    "",
  );
  assert.equal(
    mod.getBackendEnvPathInputValue({
      backendEnvPath: envPath,
      backendPath: path.join(tempDir, "server"),
    }),
    envPath,
  );

  fs.writeFileSync(
    envPath,
    [
      "# keep comments",
      "EXTRA_SETTING=keep-me",
      "OPENAI_API_KEY=old-openai-key",
      "OPENAI_BASE_URL=https://old.example/v1",
      "OLLAMA_BASE_URL=http://localhost:11434",
      "CRABBY_ADMIN_ENABLED=true",
      "CRABBY_ADMIN_TOKEN=reload-secret",
      "",
    ].join("\n"),
    "utf8",
  );

  const anthropicMap = mod.buildActiveProfileEnvMap({
    id: "profile1",
    provider: "anthropic",
    model: "claude-sonnet-4-20250514",
    baseUrl: "",
    apiKey: "anthropic-secret",
    supportsVision: false,
    thinkingMode: "enabled",
    thinkingEffort: "",
    thinkingBudgetTokens: "2048",
    reasoningSplit: false,
  });

  assert.equal(anthropicMap.OPENAI_API_KEY, null);
  assert.equal(anthropicMap.OPENAI_BASE_URL, null);
  assert.equal(anthropicMap.OLLAMA_BASE_URL, null);
  assert.equal(anthropicMap.LLM_API_KEY, "anthropic-secret");
  assert.equal(anthropicMap.LLM_BASE_URL, null);
  assert.equal(anthropicMap.ANTHROPIC_API_KEY, "anthropic-secret");
  assert.equal(anthropicMap.LLM_THINKING_MODE, "enabled");
  assert.equal(anthropicMap.LLM_THINKING_BUDGET_TOKENS, "2048");
  assert.equal(anthropicMap.LLM_REASONING_EFFORT, null);
  assert.equal(anthropicMap.LLM_REASONING_SPLIT, null);

  const openaiMap = mod.buildActiveProfileEnvMap({
    id: "profile2",
    provider: "openai",
    model: "gpt-5.4-mini",
    baseUrl: "",
    apiKey: "",
    supportsVision: false,
    thinkingMode: "",
    thinkingEffort: "high",
    thinkingBudgetTokens: "1024",
    reasoningSplit: true,
  });
  assert.equal(openaiMap.OPENAI_BASE_URL, null);
  assert.equal(openaiMap.LLM_REASONING_EFFORT, "high");
  assert.equal(openaiMap.LLM_REASONING_SPLIT, "true");

  const deepseekMap = mod.buildActiveProfileEnvMap({
    id: "profile-deepseek",
    provider: "deepseek",
    model: "deepseek-v4-flash",
    baseUrl: "https://api.deepseek.com",
    apiKey: "deepseek-secret",
    supportsVision: false,
    thinkingMode: "enabled",
    thinkingEffort: "high",
    thinkingBudgetTokens: "1024",
    reasoningSplit: false,
  });
  assert.equal(deepseekMap.LLM_PROVIDER, "deepseek");
  assert.equal(deepseekMap.LLM_BASE_URL, "https://api.deepseek.com");
  assert.equal(deepseekMap.LLM_API_KEY, "deepseek-secret");
  assert.equal(deepseekMap.DEEPSEEK_API_KEY, "deepseek-secret");
  assert.equal(deepseekMap.OPENAI_API_KEY, null);
  assert.equal(deepseekMap.ANTHROPIC_API_KEY, null);

  const deepseekNoKeyMap = mod.buildActiveProfileEnvMap({
    id: "profile-deepseek-empty-key",
    provider: "deepseek",
    model: "deepseek-v4-flash",
    baseUrl: "https://api.deepseek.com",
    apiKey: "",
    supportsVision: false,
    thinkingMode: "",
    thinkingEffort: "",
    thinkingBudgetTokens: "1024",
    reasoningSplit: false,
  });
  assert.equal(deepseekNoKeyMap.LLM_API_KEY, null);
  assert.equal(deepseekNoKeyMap.DEEPSEEK_API_KEY, null);

  const customMap = mod.buildActiveProfileEnvMap({
    id: "profile-custom",
    provider: "custom_openai",
    model: "vendor-model",
    baseUrl: "https://vendor.example/v1",
    apiKey: "custom-secret",
    supportsVision: true,
    thinkingMode: "enabled",
    thinkingEffort: "medium",
    thinkingBudgetTokens: "2048",
    reasoningSplit: true,
  });
  assert.equal(customMap.LLM_PROVIDER, "custom_openai");
  assert.equal(customMap.LLM_BASE_URL, "https://vendor.example/v1");
  assert.equal(customMap.LLM_API_KEY, "custom-secret");
  assert.equal(customMap.LLM_REASONING_SPLIT, "true");

  mod.upsertEnvFile(envPath, anthropicMap);

  const content = fs.readFileSync(envPath, "utf8");
  assert.match(content, /# keep comments/);
  assert.match(content, /EXTRA_SETTING=keep-me/);
  assert.match(content, /LLM_PROVIDER=anthropic/);
  assert.match(content, /LLM_MODEL=claude-sonnet-4-20250514/);
  assert.match(content, /LLM_API_KEY=anthropic-secret/);
  assert.match(content, /LLM_THINKING_MODE=enabled/);
  assert.match(content, /LLM_THINKING_BUDGET_TOKENS=2048/);
  assert.match(content, /ACTIVE_PROFILE_ID=profile1/);
  assert.match(content, /ANTHROPIC_API_KEY=anthropic-secret/);
  assert.doesNotMatch(content, /^LLM_REASONING_EFFORT=/m);
  assert.doesNotMatch(content, /^LLM_REASONING_SPLIT=/m);
  assert.doesNotMatch(content, /^OPENAI_API_KEY=/m);
  assert.doesNotMatch(content, /^OPENAI_BASE_URL=/m);
  assert.doesNotMatch(content, /^OLLAMA_BASE_URL=/m);

  const savedProfileMap = mod.buildSavedProfileEnvMap({
    id: "profile1",
    name: "Claude Local",
    provider: "anthropic",
    model: "claude-sonnet-4-20250514",
    baseUrl: "",
    apiKey: "anthropic-secret",
    supportsVision: false,
    thinkingMode: "enabled",
    thinkingEffort: "",
    thinkingBudgetTokens: "2048",
    reasoningSplit: false,
  });
  mod.upsertEnvFile(envPath, savedProfileMap);

  const savedContent = fs.readFileSync(envPath, "utf8");
  assert.match(savedContent, /PROFILE_profile1_NAME="Claude Local"/);
  assert.match(savedContent, /PROFILE_profile1_THINKING_MODE=enabled/);
  assert.match(savedContent, /PROFILE_profile1_THINKING_BUDGET_TOKENS=2048/);
  assert.match(savedContent, /PROFILE_profile1_REASONING_SPLIT=false/);
  mod.upsertEnvFile(envPath, {
    ACTIVE_PROFILE_ID: "profile_deepseek_env",
    PROFILE_profile1_API_KEY: "",
    PROFILE_profile_deepseek_env_NAME: "DS-Pro",
    PROFILE_profile_deepseek_env_PROVIDER: "openai",
    PROFILE_profile_deepseek_env_MODEL: "deepseek-v4-pro",
    PROFILE_profile_deepseek_env_BASE_URL: "https://api.deepseek.com",
    PROFILE_profile_deepseek_env_API_KEY: "deepseek-secret",
    PROFILE_profile_deepseek_env_SUPPORTS_VISION: "false",
    PROFILE_profile_deepseek_env_THINKING_MODE: "enabled",
    PROFILE_profile_deepseek_env_THINKING_EFFORT: "high",
    PROFILE_profile_deepseek_env_THINKING_BUDGET_TOKENS: "1024",
    PROFILE_profile_deepseek_env_REASONING_SPLIT: "false",
  });
  const profilesFromEnv = mod.readSavedProfilesFromEnv(envPath);
  const deepseekProfile = profilesFromEnv.find(
    (profile) => profile.id === "profile_deepseek_env",
  );
  assert.equal(deepseekProfile.provider, "deepseek");
  assert.equal(deepseekProfile.name, "DS-Pro");
  assert.equal(deepseekProfile.model, "deepseek-v4-pro");
  assert.equal(deepseekProfile.thinkingMode, "enabled");
  assert.equal(deepseekProfile.thinkingEffort, "high");

  const mergeSettings = {
    backendEnvPath: envPath,
    backendPath: "",
    llmProfiles: [
      {
        id: "profile1",
        name: "Old local name",
        provider: "anthropic",
        model: "old-model",
        baseUrl: "",
        apiKey: "local-secret",
        supportsVision: false,
        thinkingMode: "",
        thinkingEffort: "",
        thinkingBudgetTokens: "1024",
        reasoningSplit: false,
      },
    ],
    activeProfileId: "profile1",
  };
  assert.equal(mod.mergeSavedProfilesFromEnv(mergeSettings), true);
  assert.equal(mergeSettings.llmProfiles.length, 2);
  assert.equal(mergeSettings.llmProfiles[0].id, "profile1");
  assert.equal(mergeSettings.llmProfiles[0].name, "Claude Local");
  assert.equal(mergeSettings.llmProfiles[0].apiKey, "local-secret");
  assert.equal(mergeSettings.llmProfiles[1].id, "profile_deepseek_env");
  assert.equal(mergeSettings.llmProfiles[1].provider, "deepseek");
  assert.equal(mergeSettings.activeProfileId, "profile_deepseek_env");

  mod.upsertEnvFile(envPath, { ACTIVE_PROFILE_ID: "missing-profile" });
  const fallbackActiveSettings = {
    backendEnvPath: envPath,
    backendPath: "",
    llmProfiles: [],
    activeProfileId: "",
  };
  assert.equal(mod.mergeSavedProfilesFromEnv(fallbackActiveSettings), true);
  assert.equal(fallbackActiveSettings.activeProfileId, "profile1");
  assert.equal(mod.readEnvValue(envPath, "CRABBY_ADMIN_TOKEN"), "reload-secret");
  assert.equal(mod.isTruthyEnvValue("true"), true);
  assert.equal(mod.isTruthyEnvValue("0"), false);

  const switchSettings = {
    backendEnvPath: envPath,
    backendPath: "",
    activeProfileId: "profile1",
  };
  const targetProfile = {
    id: "profile2",
    name: "OpenAI Local",
    provider: "openai",
    model: "gpt-5.4-mini",
    baseUrl: "https://api.openai.com/v1",
    apiKey: "openai-secret",
  };

  const failedSwitch = await mod.switchActiveProfileLocally(
    switchSettings,
    targetProfile,
    {
      reloadSettings: async () => ({ ok: false, status: 403, detail: "forbidden" }),
    },
  );
  assert.equal(failedSwitch.ok, false);
  assert.equal(switchSettings.activeProfileId, "profile1");

  const successfulSwitch = await mod.switchActiveProfileLocally(
    switchSettings,
    targetProfile,
    {
      reloadSettings: async () => ({ ok: true, status: 200, detail: null }),
    },
  );
  assert.equal(successfulSwitch.ok, true);
  assert.equal(switchSettings.activeProfileId, "profile2");

  let reloadCalls = 0;
  const nextVaultPath = path.join(tempDir, "vault-a");
  const syncedVault = await mod.syncVaultPathLocally(
    {
      backendEnvPath: envPath,
      backendPath: "",
    },
    nextVaultPath,
    {
      reloadSettings: async () => {
        reloadCalls += 1;
        return { ok: true, status: 200, detail: null };
      },
    },
  );
  assert.equal(syncedVault.ok, true);
  assert.equal(syncedVault.changed, true);
  assert.equal(mod.readEnvValue(envPath, "VAULT_PATH"), path.resolve(nextVaultPath));
  assert.equal(reloadCalls, 1);

  const alreadySyncedVault = await mod.syncVaultPathLocally(
    {
      backendEnvPath: envPath,
      backendPath: "",
    },
    nextVaultPath,
    {
      reloadSettings: async () => {
        reloadCalls += 1;
        return { ok: true, status: 200, detail: null };
      },
    },
  );
  assert.equal(alreadySyncedVault.ok, true);
  assert.equal(alreadySyncedVault.changed, false);
  assert.equal(reloadCalls, 1);
}

async function testMcpConfig(mod) {
  const projectRoot = fs.mkdtempSync(path.join(os.tmpdir(), "laa-mcp-config-"));
  const envPath = path.join(projectRoot, ".env");
  const dataDir = path.join(projectRoot, "server", "data");
  const examplePath = path.join(dataDir, "mcp_servers.example.json");
  const configPath = path.join(dataDir, "mcp_servers.json");

  fs.mkdirSync(dataDir, { recursive: true });
  fs.writeFileSync(
    envPath,
    [
      "CRABBY_ADMIN_ENABLED=true",
      "CRABBY_ADMIN_TOKEN=reload-secret",
      "",
    ].join("\n"),
    "utf8",
  );
  fs.writeFileSync(
    examplePath,
    JSON.stringify(
      {
        mcpServers: {
          mempalace: {
            transport: "sse",
            url: "http://127.0.0.1:8001/sse",
          },
        },
      },
      null,
      2,
    ),
    "utf8",
  );

  const settings = {
    backendEnvPath: envPath,
    backendMcpConfigPath: "",
    backendPath: "",
  };

  const derived = mod.resolveBackendMcpConfigPath(settings);
  assert.equal(derived.ok, true);
  assert.equal(derived.configPath, configPath);
  assert.equal(derived.examplePath, examplePath);

  const missing = mod.loadMcpConfigLocally(settings);
  assert.equal(missing.ok, true);
  assert.equal(missing.exists, false);

  const created = mod.createMcpConfigFromExample(settings);
  assert.equal(created.ok, true);
  assert.equal(created.exists, true);
  assert.equal(fs.existsSync(configPath), true);

  const valid = mod.validateMcpConfigText(created.text);
  assert.equal(valid.ok, true);
  assert.deepEqual(valid.serverNames, ["mempalace"]);

  const invalid = mod.validateMcpConfigText('{"mcpServers":{"bad":{"transport":"stdio"}}}');
  assert.equal(invalid.ok, false);
  assert.match(invalid.message, /command/);

  const savedText = JSON.stringify(
    {
      mcpServers: {
        alpha: {
          transport: "stdio",
          command: "uvx",
          args: ["alpha-mcp"],
        },
      },
    },
    null,
    2,
  );
  const saved = mod.saveMcpConfigLocally(settings, savedText);
  assert.equal(saved.ok, true);
  assert.equal(fs.readFileSync(configPath, "utf8"), savedText);

  const failedReload = await mod.reloadMcpConfigLocally(settings, {
    reloadConfig: async () => ({ ok: false, status: 400, detail: "broken" }),
  });
  assert.equal(failedReload.ok, false);
  assert.match(failedReload.message, /broken/);

  const successfulReload = await mod.reloadMcpConfigLocally(settings, {
    reloadConfig: async () => ({ ok: true, status: 200, detail: null }),
  });
  assert.equal(successfulReload.ok, true);

  const statusResult = await mod.fetchMcpRuntimeStatus(settings, {
    getMcpStatus: async () => ({
      ok: true,
      status: 200,
      detail: null,
      data: {
        config_path: configPath,
        example_config_path: examplePath,
        config_exists: true,
        connected_servers: ["alpha"],
        tools_by_server: { alpha: ["alpha_tool"] },
        last_reload_ok: true,
        last_reload_error: null,
        last_reload_at: "2026-01-01T00:00:00+00:00",
      },
    }),
  });
  assert.equal(statusResult.ok, true);
  assert.match(mod.formatMcpRuntimeStatus(statusResult.status), /alpha_tool/);
}

function testSettingsData(mod) {
  const defaults = {
    backendUrl: "http://127.0.0.1:8000",
    backendEnvPath: "",
    backendMcpConfigPath: "",
    runtimeManifestUrl: "",
    backendPath: "",
    llmProfiles: [],
    activeProfileId: "",
  };
  const backendEnvPathInput = "D:\\Code\\.env";
  const backendMcpConfigPathInput = "D:\\Code\\server\\data\\mcp_servers.json";
  const legacyBackendPathInput = "D:\\legacy-backend";

  const hydrated = mod.hydrateSettings(defaults, {
    backendUrl: "  http://localhost:9000  ",
    backendEnvPath: `  ${backendEnvPathInput}  `,
    backendMcpConfigPath: `  ${backendMcpConfigPathInput}  `,
    backendPath: legacyBackendPathInput,
    llmProfiles: [
      {
        id: "profile-openai",
        name: " OpenAI Local ",
        provider: "openai",
        model: " gpt-5.4-mini ",
        baseUrl: " https://api.openai.com/v1 ",
        apiKey: " openai-secret ",
        supportsVision: "false",
        thinkingMode: " enabled ",
        thinkingEffort: " high ",
        thinkingBudgetTokens: " 2048 ",
        reasoningSplit: "true",
      },
    ],
    activeProfileId: "  profile-openai  ",
  });

  assert.equal(hydrated.backendUrl, "http://localhost:9000");
  assert.equal(hydrated.backendEnvPath, path.resolve(backendEnvPathInput));
  assert.equal(
    hydrated.backendMcpConfigPath,
    backendMcpConfigPathInput,
  );
  assert.equal(hydrated.runtimeManifestUrl, "");
  assert.equal(hydrated.backendPath, "");
  assert.equal(hydrated.activeProfileId, "profile-openai");
  assert.equal(hydrated.llmProfiles.length, 1);
  assert.equal(hydrated.llmProfiles[0].supportsVision, false);
  assert.equal(hydrated.llmProfiles[0].name, "OpenAI Local");
  assert.equal(hydrated.llmProfiles[0].model, "gpt-5.4-mini");
  assert.equal(hydrated.llmProfiles[0].baseUrl, "https://api.openai.com/v1");
  assert.equal(hydrated.llmProfiles[0].apiKey, "openai-secret");
  assert.equal(hydrated.llmProfiles[0].thinkingMode, "enabled");
  assert.equal(hydrated.llmProfiles[0].thinkingEffort, "high");
  assert.equal(hydrated.llmProfiles[0].thinkingBudgetTokens, "2048");
  assert.equal(hydrated.llmProfiles[0].reasoningSplit, true);

  const unknownProvider = mod.hydrateSettings(defaults, {
    llmProfiles: [
      {
        id: "profile-unknown",
        name: "Old Vendor",
        provider: "old-vendor",
        model: "vendor-model",
        baseUrl: "https://vendor.example/v1",
        apiKey: "vendor-secret",
      },
    ],
  });
  assert.equal(unknownProvider.llmProfiles[0].provider, "custom_openai");
  assert.equal(unknownProvider.llmProfiles[0].baseUrl, "https://vendor.example/v1");
  assert.equal(unknownProvider.llmProfiles[0].apiKey, "vendor-secret");

  const migratedLegacy = mod.hydrateSettings(defaults, {
    backendPath: legacyBackendPathInput,
  });
  assert.equal(
    migratedLegacy.backendEnvPath,
    path.resolve(legacyBackendPathInput, ".env"),
  );
  assert.equal(migratedLegacy.backendPath, "");
}

function testLlmProviders(mod) {
  assert.equal(
    mod.getReasoningEffortHint("openai"),
    "none | minimal | low | medium | high | xhigh",
  );
  assert.equal(mod.getReasoningEffortHint("deepseek"), "high | max");
  assert.equal(
    mod.getReasoningEffortHint("custom_openai"),
    "none | minimal | low | medium | high | max | xhigh",
  );
  assert.equal(mod.getReasoningEffortHint("anthropic"), "");
}

function testDefaultConfigTemplates(mod) {
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), "laa-default-config-"));
  const promptsDir = path.join(tempDir, "prompts");
  const personasDir = path.join(tempDir, "personas");
  const personaTemplateKeys = Object.keys(mod.DEFAULT_PERSONA_TEMPLATES);

  assert.deepEqual(
    personaTemplateKeys.filter((key) => key.endsWith("/PERSONA.md")).sort(),
    [
      "archivist/PERSONA.md",
      "mentor/PERSONA.md",
      "philosopher/PERSONA.md",
      "researcher/PERSONA.md",
      "secretary/PERSONA.md",
    ],
  );
  assert.deepEqual(
    personaTemplateKeys.filter((key) => key.endsWith("/METHODS.md")).sort(),
    [
      "archivist/METHODS.md",
      "mentor/METHODS.md",
      "philosopher/METHODS.md",
      "researcher/METHODS.md",
      "secretary/METHODS.md",
    ],
  );
  assert.equal(
    mod.DEFAULT_PERSONA_TEMPLATES["secretary/PERSONA.md"].includes("id: secretary"),
    true,
  );
  assert.equal(
    mod.DEFAULT_PERSONA_TEMPLATES["researcher/METHODS.md"].includes("方法论压缩"),
    true,
  );
  assert.equal(
    mod.DEFAULT_PERSONA_TEMPLATES["archivist/sources/niklas-luhmann.md"].includes("卢曼"),
    true,
  );

  const seededPrompts = mod.seedDirectoryIfEmpty(promptsDir, {
    "identity.md": "first identity\n",
    "safety.md": "first safety\n",
  });
  assert.equal(seededPrompts, true);
  assert.equal(
    fs.readFileSync(path.join(promptsDir, "identity.md"), "utf8"),
    "first identity\n",
  );

  fs.writeFileSync(path.join(promptsDir, "identity.md"), "user edited\n", "utf8");
  const reseededPrompts = mod.seedDirectoryIfEmpty(promptsDir, {
    "identity.md": "overwritten\n",
    "tool_usage.md": "new file\n",
  });
  assert.equal(reseededPrompts, false);
  assert.equal(
    fs.readFileSync(path.join(promptsDir, "identity.md"), "utf8"),
    "user edited\n",
  );
  assert.equal(fs.existsSync(path.join(promptsDir, "tool_usage.md")), false);

  const seededPersonas = mod.seedDirectoryIfEmpty(personasDir, {
    "feynman/PERSONA.md": "persona body\n",
  });
  assert.equal(seededPersonas, true);
  assert.equal(
    fs.readFileSync(path.join(personasDir, "feynman", "PERSONA.md"), "utf8"),
    "persona body\n",
  );

  const managedPersonasDir = path.join(tempDir, "managed-personas");
  const seededManagedPersonas =
    mod.seedOrMigrateDefaultPersonas(managedPersonasDir);
  assert.deepEqual(seededManagedPersonas, {
    seeded: true,
    migrated: false,
  });
  assert.equal(
    fs.existsSync(path.join(managedPersonasDir, "secretary", "PERSONA.md")),
    true,
  );
  assert.equal(
    fs.existsSync(path.join(managedPersonasDir, "secretary", "METHODS.md")),
    true,
  );

  const clutteredPersonasDir = path.join(tempDir, "cluttered-personas");
  fs.mkdirSync(clutteredPersonasDir, { recursive: true });
  fs.writeFileSync(path.join(clutteredPersonasDir, ".DS_Store"), "", "utf8");
  fs.mkdirSync(path.join(clutteredPersonasDir, "sources"), { recursive: true });
  const seededClutteredPersonas =
    mod.seedOrMigrateDefaultPersonas(clutteredPersonasDir);
  assert.deepEqual(seededClutteredPersonas, {
    seeded: true,
    migrated: false,
  });
  assert.equal(
    fs.existsSync(path.join(clutteredPersonasDir, "secretary", "PERSONA.md")),
    true,
  );
  assert.equal(
    fs.existsSync(path.join(clutteredPersonasDir, "secretary", "METHODS.md")),
    true,
  );

  const partialDefaultPersonasDir = path.join(tempDir, "partial-default-personas");
  fs.mkdirSync(path.join(partialDefaultPersonasDir, "mentor"), {
    recursive: true,
  });
  fs.writeFileSync(
    path.join(partialDefaultPersonasDir, "mentor", "PERSONA.md"),
    mod.DEFAULT_PERSONA_TEMPLATES["mentor/PERSONA.md"],
    "utf8",
  );
  const seededPartialDefaultPersonas =
    mod.seedOrMigrateDefaultPersonas(partialDefaultPersonasDir);
  assert.deepEqual(seededPartialDefaultPersonas, {
    seeded: true,
    migrated: false,
  });
  assert.equal(
    fs.existsSync(path.join(partialDefaultPersonasDir, "secretary", "PERSONA.md")),
    true,
  );
  assert.equal(
    fs.readFileSync(
      path.join(partialDefaultPersonasDir, "mentor", "PERSONA.md"),
      "utf8",
    ),
    mod.DEFAULT_PERSONA_TEMPLATES["mentor/PERSONA.md"],
  );
  assert.equal(
    fs.existsSync(path.join(partialDefaultPersonasDir, "mentor", "METHODS.md")),
    true,
  );

  const missingMethodsDir = path.join(tempDir, "missing-methods-personas");
  for (const personaId of [
    "archivist",
    "mentor",
    "philosopher",
    "researcher",
    "secretary",
  ]) {
    fs.mkdirSync(path.join(missingMethodsDir, personaId), { recursive: true });
    fs.writeFileSync(
      path.join(missingMethodsDir, personaId, "PERSONA.md"),
      mod.DEFAULT_PERSONA_TEMPLATES[`${personaId}/PERSONA.md`],
      "utf8",
    );
  }
  const seededMissingMethods =
    mod.seedOrMigrateDefaultPersonas(missingMethodsDir);
  assert.deepEqual(seededMissingMethods, {
    seeded: true,
    migrated: false,
  });
  assert.equal(
    fs.existsSync(path.join(missingMethodsDir, "researcher", "METHODS.md")),
    true,
  );
}

function testRuntimeStatePaths(mod) {
  const runtimeDir = path.join(
    os.tmpdir(),
    "CrabbyVault",
    ".obsidian",
    "plugins",
    "crabby",
    "runtime",
  );
  const executablePath = path.join(
    runtimeDir,
    "backend",
    "0.2.0",
    "darwin",
    "crabby-backend",
  );

  const statePath = mod.serializeRuntimeExecutablePath(
    runtimeDir,
    executablePath,
  );
  assert.equal(
    statePath,
    path.join("backend", "0.2.0", "darwin", "crabby-backend"),
  );
  assert.equal(
    mod.resolveRuntimeExecutablePath(runtimeDir, statePath),
    executablePath,
  );
  assert.equal(
    mod.resolveRuntimeExecutablePath(runtimeDir, executablePath),
    executablePath,
  );
  assert.equal(
    mod.resolveRuntimeExecutablePath(
      runtimeDir,
      path.join("..cache", "crabby-backend"),
    ),
    path.join(runtimeDir, "..cache", "crabby-backend"),
  );
  assert.equal(
    mod.resolveRuntimeExecutablePath(runtimeDir, path.join("..", "outside")),
    null,
  );
}

function testRuntimeDataMigration(mod) {
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), "laa-runtime-data-"));

  const legacyConfig = path.join(
    tempDir,
    "Vault",
    ".obsidian",
    "plugins",
    "crabby",
    "config",
  );
  const targetConfig = path.join(tempDir, "Vault", "crabby", "config");
  fs.mkdirSync(legacyConfig, { recursive: true });
  fs.writeFileSync(path.join(legacyConfig, ".env"), "LLM_PROVIDER=openai\n", "utf8");

  const moved = mod.migrateRuntimeDataDirectory({
    label: "config",
    legacyPath: legacyConfig,
    targetPath: targetConfig,
  });
  assert.equal(moved.status, "moved");
  assert.equal(fs.existsSync(legacyConfig), false);
  assert.equal(fs.readFileSync(path.join(targetConfig, ".env"), "utf8"), "LLM_PROVIDER=openai\n");

  const legacyData = path.join(
    tempDir,
    "Vault",
    ".obsidian",
    "plugins",
    "crabby",
    "data",
  );
  const targetData = path.join(tempDir, "Vault", "crabby", "data");
  fs.mkdirSync(path.join(legacyData, "sessions"), { recursive: true });
  fs.mkdirSync(path.join(targetData, "sessions"), { recursive: true });
  fs.writeFileSync(
    path.join(legacyData, "sessions", "new-session.json"),
    "{}",
    "utf8",
  );
  fs.writeFileSync(
    path.join(legacyData, "sessions", "conflict.json"),
    "legacy",
    "utf8",
  );
  fs.writeFileSync(
    path.join(targetData, "sessions", "conflict.json"),
    "target",
    "utf8",
  );

  const merged = mod.migrateRuntimeDataDirectory({
    label: "data",
    legacyPath: legacyData,
    targetPath: targetData,
  });
  assert.equal(merged.status, "merged");
  assert.equal(
    fs.readFileSync(path.join(targetData, "sessions", "new-session.json"), "utf8"),
    "{}",
  );
  assert.equal(
    fs.readFileSync(path.join(targetData, "sessions", "conflict.json"), "utf8"),
    "target",
  );
  assert.equal(
    fs.readFileSync(path.join(legacyData, "sessions", "conflict.json"), "utf8"),
    "legacy",
  );
}

function testSearchEngine(mod) {
  const docs = [
    {
      path: "Health/Sleep.md",
      name: "Sleep.md",
      ext: "md",
      content: [
        "# Sleep",
        "Deep sleep can be affected by caffeine.",
        "## Experiment",
        "Caffeine reduced REM sleep.",
        "- [ ] call doctor about sleep",
      ].join("\n"),
      mtime: 300,
      tags: ["#health/sleep", "#experiment"],
      aliases: ["Rest"],
      properties: {
        status: "active",
        aliases: ["Rest"],
        tags: ["#health/sleep"],
        duration: 4,
      },
      sections: [
        { text: "## Experiment\nCaffeine reduced REM sleep.", line: 3 },
      ],
      blocks: [
        { text: "Deep sleep can be affected by caffeine.", line: 2 },
      ],
      tasks: [
        { text: "- [ ] call doctor about sleep", line: 5, status: "todo" },
      ],
    },
    {
      path: "Daily/2026-04-26.md",
      name: "2026-04-26.md",
      ext: "md",
      content: "Tea after dinner made it hard to fall asleep.",
      mtime: 200,
      tags: ["#daily"],
      aliases: [],
      properties: { status: "draft" },
      sections: [],
      blocks: [],
      tasks: [],
    },
    {
      path: "Boards/Sleep.canvas",
      name: "Sleep.canvas",
      ext: "canvas",
      content: "Canvas node about sleep systems",
      mtime: 100,
      tags: [],
      aliases: [],
      properties: { type: "canvas" },
      sections: [{ text: "Canvas node about sleep systems" }],
      blocks: [{ text: "Canvas node about sleep systems" }],
      tasks: [],
    },
  ];

  const paths = (query) =>
    mod.searchDocuments(docs, { query, max_results: 10 }).results.map(
      (item) => item.path,
    );

  assert.deepEqual(paths("sleep caffeine"), ["Health/Sleep.md"]);
  assert.deepEqual(paths('"deep sleep"'), ["Health/Sleep.md"]);
  assert.equal(paths("sleep OR tea").length, 3);
  assert.deepEqual(paths("sleep -caffeine"), [
    "Boards/Sleep.canvas",
    "Daily/2026-04-26.md",
  ]);
  assert.deepEqual(paths("tag:#health/sleep"), ["Health/Sleep.md"]);
  assert.deepEqual(paths("[status:active]"), ["Health/Sleep.md"]);
  assert.deepEqual(paths("[aliases:Rest]"), ["Health/Sleep.md"]);
  assert.deepEqual(paths("[duration:<5]"), ["Health/Sleep.md"]);
  assert.deepEqual(paths("section:(caffeine REM)"), ["Health/Sleep.md"]);
  assert.deepEqual(paths("task-todo:doctor"), ["Health/Sleep.md"]);
  assert.deepEqual(paths("/caff(e|é)ine/"), ["Health/Sleep.md"]);
  assert.deepEqual(paths("file:canvas"), ["Boards/Sleep.canvas"]);
}

function testObsidianVaultResolution() {
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), "laa-obsidian-meta-"));
  const configDir = path.join(tempDir, "obsidian");
  const configPath = path.join(configDir, "obsidian.json");
  fs.mkdirSync(configDir, { recursive: true });
  fs.writeFileSync(
    configPath,
    JSON.stringify(
      {
        vaults: {
          alpha: {
            path: "D:\\Vault-A",
            ts: 100,
            open: false,
          },
          beta: {
            path: "E:\\Vault-B",
            ts: 200,
            open: true,
          },
        },
      },
      null,
      2,
    ),
    "utf8",
  );

  const previousAppData = process.env.APPDATA;
  const previousVaultPath = process.env.VAULT_PATH;

  process.env.APPDATA = tempDir;
  delete process.env.VAULT_PATH;

  const expectedOpenVaultPath = path.resolve("E:\\Vault-B");
  const fromObsidian = obsidianVault.resolveVaultForDeploy();
  assert.equal(fromObsidian.vaultPath, expectedOpenVaultPath);
  assert.equal(fromObsidian.source, "obsidian-open");

  const explicitVaultPath = "F:\\ManualVault";
  process.env.VAULT_PATH = explicitVaultPath;
  const fromEnv = obsidianVault.resolveVaultForDeploy();
  assert.equal(fromEnv.vaultPath, path.resolve(explicitVaultPath));
  assert.equal(fromEnv.source, "env");

  if (previousAppData === undefined) {
    delete process.env.APPDATA;
  } else {
    process.env.APPDATA = previousAppData;
  }

  if (previousVaultPath === undefined) {
    delete process.env.VAULT_PATH;
  } else {
    process.env.VAULT_PATH = previousVaultPath;
  }
}

async function main() {
  const backendConfig = await loadModule("config/backendConfig.ts", "backend-config.cjs");
  const llmProviders = await loadModule("config/llmProviders.ts", "llm-providers.cjs");
  const mcpConfig = await loadModule("config/mcpConfig.ts", "mcp-config.cjs");
  const settingsData = await loadModule("config/settingsData.ts", "settings-data.cjs");
  const defaultConfigTemplates = await loadModule(
    "runtime/defaultConfigTemplates.ts",
    "default-config-templates.cjs",
  );
  const runtimeState = await loadModule(
    "runtime/runtimeState.ts",
    "runtime-state.cjs",
  );
  const runtimeDataMigration = await loadModule(
    "runtime/runtimeDataMigration.ts",
    "runtime-data-migration.cjs",
  );
  const searchEngine = await loadModule("search/searchEngine.ts", "search-engine.cjs");

  await testBackendConfig(backendConfig);
  await testMcpConfig(mcpConfig);
  testSettingsData(settingsData);
  testLlmProviders(llmProviders);
  testDefaultConfigTemplates(defaultConfigTemplates);
  testRuntimeStatePaths(runtimeState);
  testRuntimeDataMigration(runtimeDataMigration);
  testSearchEngine(searchEngine);
  testObsidianVaultResolution();

  console.log(
    "backendConfig, llmProviders, mcpConfig, settingsData, runtime state, runtime data migration, default template, and search tests passed",
  );
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
