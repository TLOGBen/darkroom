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

## 1. Check the machine

| Requirement | How to check | If it fails |
|---|---|---|
| Windows 10 / 11 | `cmd /c ver` | macOS / Linux are not supported yet. Tell the person and stop. |
| NVIDIA GPU | `nvidia-smi` prints a GPU and a driver | darkroom currently needs CUDA. Tell the person and stop. |
| Python 3.13 | `py -3.13 --version` (or `python3.13 --version`) | Ask the person to install Python 3.13 from python.org, then re-check. |
| git | `git --version` | Ask the person to install Git for Windows. |
| Node.js (optional) | `node --version` | Only needed to run the frontend tests; skip if absent. |

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

must print `True` and the GPU name. If it prints `False`, stop and show the person.

## 4. Point darkroom at the presets

Ask the person: *"Where are your Lightroom `.xmp` presets? (a folder; sub-folders are fine)"*

Verify the folder exists and contains `.xmp` files (count them and tell the person). Then create
`config.local.json` in the repository root (it is git-ignored):

```json
{
  "preset_dir": "D:/Presets/xmp"
}
```

Optional keys — only set them if the person asks:

| Key | Meaning | Default |
|---|---|---|
| `preset_library_dir` | where the preset library index, imported and self-saved presets live | the parent of `preset_dir` |
| `data_dir` | the photo library: per-photo edits and thumbnail cache | `%LOCALAPPDATA%\darkroom` |
| `anthropic_api_key_ref` | a 1Password reference (`op://<vault>/<item>/credential`) to an Anthropic API key, read with `op read` only when `presets semantic build` runs. Never put the key itself in this file; `DARKROOM_ANTHROPIC_API_KEY` in the environment is the alternative | unset: the semantic index stays off |
| `semantic_index_budget_usd` | the most one `presets semantic build` may cost (estimated before anything is sent) | `5` |
| `calibration_sources_dir` | the four public calibration photos the semantic index renders presets on | `<localllms_root>/scratch/lr-calibration/sources` |

`preset_library_dir` and `data_dir` must **not** be inside a photo folder or inside `preset_dir`.

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

## 6. Start the app

```powershell
.\.venv\Scripts\python.exe -s -m darkroom_app
```

Then open <http://127.0.0.1:8765/>. Use `--port` for another port (not 80), `--preset-dir` /
`--data-dir` to override the config for one run.

**Check:** `Invoke-WebRequest http://127.0.0.1:8765/api/health -UseBasicParsing` returns `{"ok": true}`.
Stop the server afterwards if the person did not ask to keep it running.

## 7. (Optional) Register the MCP server

Ask the person whether they want their agent to drive darkroom directly. If yes:

```powershell
claude mcp add darkroom -- "<absolute path to repo>\.venv\Scripts\python.exe" -s -m darkroom_app.mcp_server
```

(Other MCP clients: a stdio server, command = the venv's `python.exe`, args =
`-s -m darkroom_app.mcp_server`, working directory = the repository root.)

**Check:** the client lists 27 tools named `darkroom_*` (the 25th is `darkroom_edit_restore`, the MCP twin of
`edit restore`; the last two are `darkroom_semantic_build` and `darkroom_semantic_status`); calling `darkroom_presets_list` with
`{"limit": 3}` returns presets.

## 8. Tell the person what you did

Summarise: the clone path, the Python and PyTorch versions, the preset folder and how many presets
were found, the test result, how to start the app, and whether MCP was registered.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `darkroom：找不到 LocalLLMs 的位置…` or `preset folder not found` | `config.local.json` is missing or `preset_dir` is wrong. |
| `torch.cuda.is_available()` is `False` | CPU-only torch was installed, or the driver is too old. Reinstall from the CUDA index in step 3. |
| HEIC photos are refused | `pillow-heif` is not installed; it is optional (`pip install pillow-heif==1.8.0`). |
| Every request answers 421 / 403 | You opened the app through another host name or port 80. Use `http://127.0.0.1:<port>/`. |
| A preset shows "settings that cannot be applied" | Expected for some presets (camera profiles, Adobe Looks, absolute white balance); the rest of the preset still applies. |

## For the curious agent

- Domain terms: [`CONTEXT.md`](../CONTEXT.md). Architecture decisions: [`docs/adr/`](adr/).
- Every feature has an acceptance contract in [`.claude/contract/`](../.claude/contract/).
- CLI exit codes: `0` ok, `1` unexpected, `2` invalid, `3` not found, `4` conflict, `5` unavailable,
  `6` partial failure in a batch. With `--json`, stdout is exactly one JSON line.
