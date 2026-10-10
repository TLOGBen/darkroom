// darkroom first-run page logic. Talks to the Rust side (desktop/src-tauri/src/main.rs) through Tauri's global
// API (`app.withGlobalTauri`), so no bundler or npm package is needed:
//   runtime_status  -> {state: ready|missing|outdated, external, install_dir, app_version, installed_version,
//                       torch: cuda|cpu|default, download_mb, disk_mb}
//   install_runtime -> resolves when done; progress arrives as "setup-progress" events {phase, step, total, line}
//   cancel_install  -> stops the running install (the pending install_runtime then rejects with code "cancelled")
//   preset_setup_status -> {configured, preset_dir, config_file}: is a usable preset folder configured?
//   set_preset_dir  -> writes the picked folder through the backend's own `settings set` (its checks apply)
//   plugin:dialog|open -> the native folder picker (tauri-plugin-dialog)
//   start_backend   -> starts Python and navigates this window to the editor (this page disappears)
// The backend cannot start without a preset folder, and an installed copy has no config.local.json to edit and no
// `darkroom` CLI, so this page asks for the folder before starting (and offers it again when a start fails).
// Errors are {code, detail}: the code picks a translated sentence, the detail is shown verbatim below it.
"use strict";

(function () {
  const TORCH_VERSION = "2.14.0"; // shown to the user only; the pin itself lives in src-tauri/src/paths.rs
  const MAX_LOG_LINES = 300;

  const lang = /^zh\b/i.test(navigator.language || "") ? "zh-TW" : "en-US";
  const strings = window.DARKROOM_I18N[lang];
  document.documentElement.lang = lang;

  /** Translated string with {placeholders} filled. */
  function t(key, vars) {
    let s = strings[key] ?? key;
    for (const [k, v] of Object.entries(vars || {})) s = s.replaceAll(`{${k}}`, String(v));
    return s;
  }

  const $ = (id) => document.getElementById(id);

  function applyStaticText() {
    for (const el of document.querySelectorAll("[data-i18n]")) el.textContent = t(el.dataset.i18n);
  }

  function show(viewId) {
    for (const v of document.querySelectorAll(".view")) v.hidden = v.id !== viewId;
  }

  function busy(key) {
    $("busy-text").textContent = t(key);
    show("view-busy");
  }

  /** "about 3.0 GB" / "about 450 MB" from a megabyte count. */
  function size(mb) {
    const text = mb >= 1000 ? `${(mb / 1000).toFixed(1)} GB` : `${mb} MB`;
    return t("about", { size: text });
  }

  function problem(err, titleKey, bodyKey) {
    const code = err && err.code ? err.code : "unknown";
    $("problem-title").textContent = t(titleKey || "problemTitle");
    const key = bodyKey || `err_${code}`;
    $("problem-body").textContent = t(key in strings ? key : "err_unknown");
    const detail = err == null ? "" : typeof err === "object" ? err.detail : String(err);
    $("problem-detail").textContent = detail || "";
    $("problem-detail").hidden = !detail;
    show("view-problem");
  }

  const tauri = window.__TAURI__;
  if (!tauri || !tauri.core) {
    applyStaticText();
    $("busy-text").textContent = t("notInApp");
    return;
  }
  const invoke = tauri.core.invoke;
  let status = null;
  let retry = check;

  async function check() {
    busy("checking");
    try {
      status = await invoke("runtime_status");
    } catch (err) {
      retry = check;
      problem(err);
      return;
    }
    $("version").textContent = t("version", { v: status.app_version });
    if (status.state === "ready") {
      await presetsThenStart();
    } else {
      showConsent();
    }
  }

  function showConsent() {
    const outdated = status.state === "outdated";
    $("consent-title").textContent = t(outdated ? "consentTitleOutdated" : "consentTitleMissing");
    $("consent-lead").textContent = outdated
      ? t("consentLeadOutdated", { v: status.app_version, old: status.installed_version || "?" })
      : t("consentLeadMissing");
    const small = outdated && status.download_mb <= 100;
    $("fact-what").textContent = small
      ? t("whatUpdate")
      : t(status.torch === "cuda" ? "whatCuda" : "whatCpu", { torch: TORCH_VERSION });
    $("fact-download").textContent = size(status.download_mb);
    $("fact-disk").textContent = size(status.disk_mb);
    $("fact-where").textContent = status.install_dir;
    const gpu = t(status.torch === "cuda" ? "gpuCuda" : status.torch === "cpu" ? "gpuCpu" : "gpuDefault");
    $("gpu-note").textContent = gpu;
    $("gpu-note").hidden = !gpu;
    show("view-consent");
  }

  const STEPS = ["python", "torch", "darkroom"];

  function markStep(phase) {
    const idx = STEPS.indexOf(phase);
    if (idx < 0) return;
    for (const li of document.querySelectorAll(".steps li")) {
      const i = STEPS.indexOf(li.dataset.step);
      li.classList.toggle("done", i < idx);
      li.classList.toggle("active", i === idx);
    }
    // Weighted by how long each step usually takes (torch dominates); CSSOM width is allowed by the CSP.
    const weights = [0.05, 0.85, 0.1];
    const before = weights.slice(0, idx).reduce((a, b) => a + b, 0);
    $("bar-fill").style.width = `${Math.round((before + weights[idx] * 0.15) * 100)}%`;
  }

  function appendLog(line) {
    const log = $("log");
    const lines = (log.textContent ? log.textContent.split("\n") : []).concat(line);
    log.textContent = lines.slice(-MAX_LOG_LINES).join("\n");
    log.scrollTop = log.scrollHeight;
  }

  async function install() {
    $("log").textContent = "";
    $("btn-cancel").disabled = false;
    $("btn-cancel").textContent = t("cancel");
    for (const li of document.querySelectorAll(".steps li")) li.classList.remove("done", "active");
    $("bar-fill").style.width = "0%";
    show("view-install");
    const unlisten = await tauri.event.listen("setup-progress", (event) => {
      const p = event.payload;
      markStep(p.phase);
      if (p.line) appendLog(p.line);
    });
    try {
      await invoke("install_runtime");
      $("bar-fill").style.width = "100%";
      await presetsThenStart();
    } catch (err) {
      retry = install;
      if (err && err.code === "cancelled") {
        problem(null, "cancelledTitle", "cancelledBody");
      } else {
        problem(err);
      }
    } finally {
      unlisten();
    }
  }

  // ---- the preset folder (before the first start) ----
  let chosenDir = null;

  /** Asks whether a usable preset folder is configured; starts the backend when it is, else asks for one. */
  async function presetsThenStart() {
    busy("checkingPresets");
    let setup;
    try {
      setup = await invoke("preset_setup_status");
    } catch (err) {
      retry = presetsThenStart;
      problem(err);
      return;
    }
    if (setup.configured) {
      await start();
    } else {
      showPresets(setup);
    }
  }

  function showPresets(setup) {
    chosenDir = null;
    const missing = setup && setup.preset_dir && !setup.configured;
    $("presets-missing").textContent = missing ? t("presetsMissing", { dir: setup.preset_dir }) : "";
    $("presets-missing").hidden = !missing;
    $("presets-chosen").textContent = t("presetsNone");
    $("presets-config").textContent = (setup && setup.config_file) || "";
    presetsError("");
    $("btn-presets-use").disabled = true;
    show("view-presets");
  }

  function presetsError(text) {
    $("presets-error").textContent = text;
    $("presets-error").hidden = !text;
  }

  async function pickPresets() {
    presetsError("");
    let dir;
    try {
      // The dialog plugin's own command (what window.__TAURI__.dialog.open calls).
      dir = await invoke("plugin:dialog|open", { options: { directory: true, multiple: false } });
    } catch (err) {
      presetsError(t("presetsPickerFailed", { reason: (err && err.detail) || String(err) }));
      return;
    }
    if (typeof dir !== "string" || !dir) return; // the user closed the picker
    chosenDir = dir;
    $("presets-chosen").textContent = dir;
    $("btn-presets-use").disabled = false;
  }

  async function usePresets() {
    if (!chosenDir) return;
    $("btn-presets-use").disabled = true;
    presetsError("");
    try {
      const setup = await invoke("set_preset_dir", { path: chosenDir });
      if (!setup.configured) {
        presetsError(t("presetsMissing", { dir: setup.preset_dir || chosenDir }));
        $("btn-presets-use").disabled = false;
        return;
      }
    } catch (err) {
      // Our sentence, then the backend's own reason verbatim (e.g. the folder does not exist).
      const key = err && err.code === "settings_refused" ? "err_settings_refused" : "err_unknown";
      presetsError(t(key) + "\n" + ((err && err.detail) || String(err)));
      $("btn-presets-use").disabled = false;
      return;
    }
    await start();
  }

  async function start() {
    busy("starting");
    try {
      // On success the window navigates to the editor and this page is gone.
      await invoke("start_backend");
    } catch (err) {
      retry = start;
      problem(err);
      // A start that fails is often a preset folder that moved: let the user pick another one from here.
      $("btn-presets-again").hidden = false;
    }
  }

  applyStaticText();
  $("btn-agree").addEventListener("click", install);
  $("btn-decline").addEventListener("click", () => show("view-declined"));
  $("btn-back").addEventListener("click", showConsent);
  $("btn-retry").addEventListener("click", () => {
    $("btn-presets-again").hidden = true;
    retry();
  });
  $("btn-presets-again").addEventListener("click", () => {
    $("btn-presets-again").hidden = true;
    showPresets(null);
  });
  $("btn-presets-pick").addEventListener("click", pickPresets);
  $("btn-presets-use").addEventListener("click", usePresets);
  $("btn-cancel").addEventListener("click", async () => {
    $("btn-cancel").disabled = true;
    $("btn-cancel").textContent = t("cancelling");
    await invoke("cancel_install");
  });
  check();
})();
