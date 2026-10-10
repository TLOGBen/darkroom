# Installing darkroom — a guide for coding agents

This page is written for an AI coding agent (Claude Code, Codex, Cursor, …) that a person asked to
install darkroom on their machine. Follow it top to bottom. Each step has a **check**; do not move on
until the check passes. Where a step needs a decision only the person can make, **ask them** — the
questions are spelled out below. Never guess a folder path.

## Ground rules

- **Never write into the person's photo folders or preset folders.** darkroom only reads them; you
  must not copy, move, rename or "organise" them either.
- **Do not change system-wide Python, PATH, or another project's environment.** Use a virtual
  environment inside the clone (step 3).
- **Ask before installing anything large** (PyTorch with CUDA is ~2–3 GB).
- **Report honestly.** If a check fails, show the person the exact output and stop.
- darkroom binds to `127.0.0.1` only. Do not expose it on the network.

## 0. Installer or source?

This guide installs darkroom **from source** (a git clone and a `.venv`). If the person only wants to edit photos,
the desktop installer is simpler: point them to the [GitHub Releases](https://github.com/TLOGBen/darkroom/releases)
(Windows `.msi` / `-setup.exe`, Linux `.deb` / `.AppImage`) and [`docs/install.md`](install.md). The installed app asks
before downloading Python and PyTorch (about 3 GB) on its first launch.

With the installer, the command-line launcher `darkroom` (`darkroom-<version>-windows-x64.exe` /
`darkroom-<version>-linux-x64.tar.gz` on the same release page) replaces `python -s -m darkroom_app.cli` everywhere
in this repository's docs: `darkroom presets list --json`, `darkroom mcp` (the MCP server), `darkroom app` (the web
app), `darkroom --version`. It finds the app's managed environment (or the interpreter in `DARKROOM_PYTHON`) and exits
`5` with one bilingual line when there is none. The installed app currently does not start until a preset folder is
set; set it with `darkroom settings set preset_dir=<folder the person named>` and ask them to reopen the app.

## 1. Check the machine

| Requirement | How to check | If it fails |
|---|---|---|
| Windows 10 / 11 (or Linux x64) | `cmd /c ver` | macOS is not supported yet: tell the person and stop. On Linux the steps are the same with `./.venv/bin/python` (this guide shows Windows). |
| NVIDIA GPU | `nvidia-smi` prints a GPU and a driver | Without one darkroom renders on the CPU (works, but much slower). Tell the person and ask whether to continue with the CPU build of PyTorch (`--index-url https://download.pytorch.org/whl/cpu` in step 3). |
| Python 3.13 | `py -3.13 --version` (or `python3.13 --version`) | Ask the person to install Python 3.13 from python.org, then re-check. |
| git | `git --version` | Ask the person to install Git for Windows. |
| Node.js 22+ with npm | `node --version`, `npm --version` | Needed once to build the web page (`web/dist`, step 6) and for the frontend tests. Ask the person to install Node.js LTS from nodejs.org. |

**Check:** you can state the GPU name, driver version, and Python version back to the person.

## 2. Get the code

```powershell
git clone https://github.com/TLOGBen/darkroom.git
cd darkroom
```

**Check:** `git log -1 --oneline` prints a commit.

## 3. Create the environment

Ask the person: *"Installing PyTorch with CUDA downloads about 2–3 GB. OK to proceed?"*

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install torch==2.14.0 --index-url https://download.pytorch.org/whl/cu130
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

If `torch==2.14.0` / `cu130` is not available for their driver, pick the newest CUDA build PyTorch
offers that `nvidia-smi`'s "CUDA Version" supports, tell the person which one you chose, and continue.

**Check:**

```powershell
.\.venv\Scripts\python.exe -c "import torch; print(torch.__version__, torch.cuda.is_available(), torch.cuda.get_device_name(0))"
```

must print `True` and the GPU name. If it prints `False`, stop and show the person. (Only when the person agreed to
the CPU build in step 1: check `python -c "import torch; print(torch.__version__)"` instead.)

## 4. Point darkroom at the presets

Ask the person: *"Where are your Lightroom `.xmp` presets? (a folder; sub-folders are fine)"*

Verify the folder exists and contains `.xmp` files (count them and tell the person). Then write it into the
settings file with the CLI (the `settings` commands work before any preset folder is configured; every value is
checked before anything is written):

```powershell
.\.venv\Scripts\python.exe -s -m darkroom_app.cli settings set preset_dir=D:/Presets/xmp --json
```

This creates `config.local.json` in the repository root (git-ignored) when no other settings file exists
(`DARKROOM_CONFIG`, if set, wins; `settings get --json` prints the file in use as `config_file`). Writing the file by
hand works too:

```json
{
  "preset_dir": "D:/Presets/xmp"
}
```

Optional keys — only set them if the person asks (all keys and their checks: [`configuration.md`](configuration.md)):

| Key | Meaning | Default |
|---|---|---|
| `preset_library_dir` | where the preset library index, imported and self-saved presets live | the parent of `preset_dir` |
| `data_dir` | the photo library: per-photo edits, thumbnail cache and saved export presets | Windows `%LOCALAPPDATA%\darkroom`; macOS `~/Library/Application Support/darkroom`; Linux and others `$XDG_DATA_HOME/darkroom` (an absolute `XDG_DATA_HOME` only), else `~/.local/share/darkroom` |
| `language` | the interface language, `zh-TW` or `en-US` | `zh-TW` |
| `agent.api_key_ref` (old name `anthropic_api_key_ref`, still read) | a 1Password reference (`op://<vault>/<item>/credential`) to an Anthropic API key, read with `op read` only when `presets semantic build` runs. Never put the key itself in the settings (`settings set` refuses values that look like a key); `DARKROOM_ANTHROPIC_API_KEY` in the environment is the alternative | unset: the semantic index stays off |
| `agent.budget_usd` (old name `semantic_index_budget_usd`, still read) | the most one `presets semantic build` may cost (estimated before anything is sent) | `5` |
| `comfyui_url` | ComfyUI's API, loopback addresses only | `http://127.0.0.1:8188` |
| `calibration_sources_dir` | the four public calibration photos the semantic index renders presets on | `<localllms_root>/scratch/lr-calibration/sources` |

`preset_library_dir` and `data_dir` must **not** be inside a photo folder or inside `preset_dir`. Relative paths in
`preset_dir`, `preset_library_dir` and `data_dir` are taken relative to the folder of `config.local.json`
(`--preset-dir` / `--data-dir` on the command line: relative to the current directory). A `config.local.json` that is
not valid JSON is reported in one line naming the line and column (`config.local.json 不是正確的 JSON（第 3 行第 5 欄）：…`).
If the preset library root itself lies in a photo folder (a folder holding photos directly, other than a drive root,
the home folder or the temp folder), organising, importing and saving presets are switched off with that reason;
set `preset_library_dir` to another folder.

**Check:**

```powershell
.\.venv\Scripts\python.exe -s -m darkroom_app.cli presets list --limit 3 --json
```

prints one line starting with `{"ok":true` and lists presets.

## 5. Run the tests (recommended)

```powershell
.\.venv\Scripts\python.exe -s -m unittest discover -s tests
```

Expect `OK` (a few timing tests are skipped automatically while the GPU is busy). It takes a few
minutes. Tests only write inside temporary folders; a guard fails any test that writes elsewhere.

**Check:** the last lines say `OK` (with or without `skipped=`). If anything fails, show the person
the failing test names and stop.

## 6. Build the page, then start the app

The editor page is a React app in `web/`; the server only serves its build (`web/dist`). Build it once (about 1-3
minutes the first time, mostly downloading npm packages), and again after pulling front-end changes:

```powershell
cd web; npm ci; npm run build; cd ..
.\.venv\Scripts\python.exe -s -m darkroom_app
```

Without the build the API still works but the page answers HTTP 503 with these same instructions.

Then open <http://127.0.0.1:8765/>. Use `--port` for another port (not 80), `--preset-dir` /
`--data-dir` to override the config for one run.

**Check:** `Invoke-WebRequest http://127.0.0.1:8765/api/health -UseBasicParsing` returns `{"ok": true}`, and
`.\.venv\Scripts\python.exe -s -m darkroom_app.cli --version` prints `darkroom <version>`
(`version --json` adds the Python, torch and CUDA versions).
Stop the server afterwards if the person did not ask to keep it running.

## 7. (Optional) Register the MCP server

Ask the person whether they want their agent to drive darkroom directly. If yes:

```powershell
claude mcp add darkroom -- "<absolute path to repo>\.venv\Scripts\python.exe" -s -m darkroom_app.mcp_server
```

(Other MCP clients: a stdio server, command = the venv's `python.exe`, args =
`-s -m darkroom_app.mcp_server`, working directory = the repository root. With the installer:
`claude mcp add darkroom -- "<path to darkroom.exe>" mcp`.)

**Check:** the client lists 38 tools named `darkroom_*` (the 25th is `darkroom_edit_restore`, the MCP twin of
`edit restore`; the 26th and 27th are `darkroom_semantic_build` and `darkroom_semantic_status`; the 33rd is
`darkroom_capabilities`; the 34th-38th are `darkroom_settings_get` / `_set` / `_export` / `_import` and
`darkroom_version`); calling `darkroom_presets_list` with `{"limit": 3}` returns presets.

## 8. Tell the person what you did

Summarise: the clone path, the Python and PyTorch versions, the preset folder and how many presets
were found, the test result, how to start the app, and whether MCP was registered.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `darkroom：還沒設定 preset 資料夾…` or `preset folder not found` | No preset folder is configured, or `preset_dir` is wrong. `settings get --json` shows the settings file in use and its values; fix with `settings set preset_dir=…`. |
| `… 不是正確的 JSON（第 N 行第 M 欄）…` | The settings file was hand-edited into invalid JSON; fix that line. darkroom never overwrites a broken settings file. |
| `torch.cuda.is_available()` is `False` | CPU-only torch was installed, or the driver is too old. Reinstall from the CUDA index in step 3. |
| HEIC photos are refused | `pillow-heif` is not installed; it is optional (`pip install pillow-heif==1.8.0`). |
| Something is greyed out in the app | Run `python -s -m darkroom_app.cli capabilities`: every switched-off feature (gpu, heic, webp, photo_library, preset_library_writes, semantic_index, onepassword, comfyui, agent_sdk) is listed with its reason. With `anthropic_api_key_ref` set it runs `op whoami` once (sign-in check only, never reads a secret). |
| Every request answers 421 / 403 | You opened the app through another host name or port 80. Use `http://127.0.0.1:<port>/`. |
| A preset shows "settings that cannot be applied" | Expected for some presets (camera profiles, Adobe Looks, absolute white balance); the rest of the preset still applies. |

## For the curious agent

- Domain terms: [`CONTEXT.md`](../CONTEXT.md). Architecture: [`architecture.md`](architecture.md); decisions:
  [`docs/adr/`](adr/). Settings: [`configuration.md`](configuration.md).
- Every feature has an acceptance contract in [`.claude/contract/`](../.claude/contract/).
- CLI exit codes: `0` ok, `1` unexpected, `2` invalid, `3` not found, `4` conflict, `5` unavailable,
  `6` partial failure in a batch. With `--json`, stdout is exactly one JSON line.
