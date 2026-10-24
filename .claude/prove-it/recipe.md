# darkroom — prove-it recipe

Read cold by the next /prove-it run. darkroom is a local photo editor: a Python backend with three entry points that
share one facade (ADR-0001) — the Web App (HTTP on 127.0.0.1, the page is `web/dist`), the CLI, and the MCP stdio
server an AI agent uses. Every command below was run on Windows 11 with pwsh 7 and Git Bash (2026-10-24).

## Surface

- **Primary**: the Web App. The page's buttons call JSON routes through `web/src/requests/*.ts` (for example
  「還原成原圖」→ `DELETE /api/edit?path=`, 「取回上一份」→ `POST /api/edit/restore {path}`, autosave →
  `PUT /api/edit`). A proof may drive those routes with plain HTTP when the claim is about what the server does with
  the request; a claim about what the page shows needs the browser (not mapped yet).
- **AI agent**: the MCP stdio server (`darkroom_app.mcp_server`, 38 `darkroom_*` tools), always another process.
- **CLI**: `darkroom_app.cli <command> --json`, one line `{"ok":…}`; used here as the independent read-back.

## Python (read this first)

`PY = E:/llm/runtimes/darkroom-python/py3.13.14-torch2.14.0-cu130/python.exe` (from `config.local.json`
`localllms_root`; E: is a removable disk, nothing runs without it). Always `-s`.

That Python is an embeddable build: `python313._pth` fixes `sys.path`, so the working directory and `PYTHONPATH` are
ignored. Its `._pth` still names the repo's old place `D:/Code/darkroom` (which no longer exists), so
`PY -s -m darkroom_app…` from the repo root fails with `No module named darkroom_app` (this is also why
`tests/test_app_launch.py` `test_start_ps1_runs_server_on_given_port` fails). Until that file is fixed (an
environment change for the user to make), run every module through the shipped helper, which puts a chosen checkout
first on `sys.path` and runs the module as `-m` would:

```
PY -s .claude/prove-it/tools/run_module.py --repo <checkout> darkroom_app.cli --version
```

`python -s -m unittest discover -s tests` is not affected (discover adds the top-level folder itself).

## Launch

Disposable state per run, never the user's: a preset folder with a few synthetic xmp files (`tests/_xmpgen.py`,
e.g. `p-expo` Exposure +1.00, `p-strong` +4.50), synthetic photos, and an empty `data_dir`, all under the run's own
folder. Pass them on the command line so the user's `config.local.json`, `%LOCALAPPDATA%/darkroom` and preset library
are never read or written.

- App: `PY -s .claude/prove-it/tools/run_module.py --repo <checkout> darkroom_app --port <free port> --preset-dir <presets> --data-dir <data>`
  (or `gated_app.py`, below, for forced-order claims). **Ready** when stdout prints
  `darkroom 已啟動：http://127.0.0.1:<port>/` (about 3 s; the GPU warm-up runs after that in the background).
  Without `web/dist` the page is a 503 notice but every `/api/*` route works.
- MCP: `PY -s .claude/prove-it/tools/run_module.py --repo <checkout> darkroom_app.mcp_server --preset-dir <presets> --data-dir <data>`;
  stderr prints `[darkroom-mcp] ready (stdio)`; send `initialize`, then `notifications/initialized`. The facade is
  built on the first `tools/call` (about 0.2 s here), so warm it with a read-only call (`darkroom_edit_get`) before
  timing anything.
- A worktree of another commit is a valid `<checkout>` (`git worktree add --detach <scratch>/wt-<sha> <sha>`); the
  helper imports that tree's `darkroom_app`.

Teardown: terminate the App process you started (Windows reports exit 1 for `terminate`), close the MCP server's
stdin (it exits 0), remove the run's disposable folder.

## Doctor

Read-only, before the first drive:
1. `GET /api/health` with `X-Darkroom: 1` → `{"ok": true}`.
2. The App runs the intended checkout: `gated_app.py` writes the imported `darkroom_app/__init__.py` path to
   `<gate-dir>/app-module.txt`; it must lie inside `<checkout>`. `git -C <checkout> rev-parse HEAD` and
   `git status --porcelain -- darkroom_app` name the version.
3. The port is the one you chose and the App is the process you started (never drive an instance you did not start;
   two instances on different ports with different data_dirs are fine side by side).
4. When a hypothesis covers the claim: `java -version` works and `D:\Workspace\00_Env\tla\tla2tools.jar` exists.

## Drive

- HTTP: every request carries `X-Darkroom: 1` and `Content-Type: application/json`, Host `127.0.0.1:<port>`
  (other hosts are refused with 421/403 by design). Routes: `web/src/requests/*.ts` and
  `darkroom_app/adapters/http/server.py:497-533`.
- MCP: one JSON-RPC message per line on stdin/stdout; `tools/call {name, arguments}`; a refused call is a normal
  result with `isError: true` and the service's sentence.
- Forced order (timing claims): `.claude/prove-it/tools/gated_app.py` starts the unchanged App with a gate after
  chosen `EditStore` reads; the driver arms a gate with a file, waits for `paused-<gate>`, acts from another entry
  point, then releases with `go-<gate>`. This is the only instrumentation; record it as such in every record.
- Ready-made driver for the photo-edit races: `.claude/prove-it/tools/photo_edit_race.py` (see
  `features/photo-edit.md`).

## Evidence

Per claim: the transcript of every request and answer with timings, the App and MCP logs, the stored state read back
through a second view (`GET /api/edit` from the App **and** `darkroom_app.cli edit get --json` as a third process),
and the raw files under `<data>/edits/`. Write evidence under a working folder, move it beside the record in
`.claude/prove-it/records/<short-sha>-<slug>/` once complete.

## Cleanup

Stop only the processes the run started, by their handles (`photo_edit_race.py` does this in `finally`); remove the
disposable `run/` folder; remove worktrees you added (`git worktree remove <path>`). Never remove evidence.

## Hypotheses

Before driving a claim about order or every case: `python D:\Workspace\01_Plugin\baransu\plugins\baransu\skills\hypothesis\scripts\hypothesis-status.py --files <files>`
(set `PYTHONIOENCODING=utf-8` on Windows or the Chinese text is garbled), then act per the hypothesis skill's
`references/reading.md` § State × reader. Covered today: `photo-edit` (`.claude/hypothesis/photo-edit/`).

## Proved

This recipe was proved end to end on 2026-10-24 (launch, doctor, drive of `features/photo-edit.md`, evidence, cleanup)
against 4afcc58 (a worktree) and e4550aa; records `records/4afcc58-photo-edit-race.md` and
`records/e4550aa-photo-edit-race.md`.
