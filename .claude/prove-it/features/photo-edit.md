# Photo edit: save, reset to original, restore previous

A photo's edit (preset × strength + tweaks + crop) is kept in the photo library by the photo's content fingerprint.
The user saves it (autosave), resets the photo to original (the edit is kept as the "previous" one), and restores the
previous edit; an AI agent can do the same on the same photo at the same time through MCP.

## Sub-features

- `edit-save` saves or replaces the edit (`PUT /api/edit`; MCP `darkroom_edit_set`; CLI `edit set`).
- `edit-clear` resets to original and keeps the edit as the previous one (`DELETE /api/edit?path=`; MCP
  `darkroom_edit_clear`; CLI `edit clear`); with no edit it does nothing.
- `edit-restore` puts the previous edit back, refused with a conflict when another edit is there
  (`POST /api/edit/restore`; MCP `darkroom_edit_restore`; CLI `edit restore`).
- `edit-get` reads the edit and whether a previous one exists (`GET /api/edit?path=`; MCP `darkroom_edit_get`; CLI
  `edit get`).
- `edit-race` the App and the agent on one photo at once (hypothesis `photo-edit`, rules R1 and R2).

## How to get to it (user POV)

- Web App, editor: changing a preset or a slider autosaves; top bar 「還原成原圖」 and 「取回上一份」.
- Web App, thumbnail grid: select photos, 「還原成原圖」, 「取回上一份」.
- AI agent: the MCP tools above, or the CLI with `--json`.

## Driving it with HTTP + MCP

Preconditions: the baseline; presets `p-expo` (Exposure +1.00) and `p-strong` (+4.50); one photo `a.jpg`.

- **Save.** `PUT /api/edit {"path": a, "preset_id": "p-expo", "strength": 130}` → 200, `edit.preset.id` `p-expo`,
  `previous: false`; `<data>/edits/<fp[:2]>/<fp>.json` exists.
- **Clear.** `DELETE /api/edit?path=a` → 200, `edit: null`, `previous: true`; `<fp>.prev.json` holds the cleared edit.
- **Restore.** `POST /api/edit/restore {"path": a}` → 200 with the previous edit. Not yet driven live (expected from
  the code and `tests/test_photo_library.py`): restoring again is a no-op success; after saving another edit it is a
  conflict 「這張照片已經有別的編輯，取回上一份會蓋掉它；要取回請先還原成原圖：a.jpg」.
- **Read back.** `GET /api/edit?path=a` and `run_module.py --repo <checkout> darkroom_app.cli --preset-dir … --data-dir … edit get a --json`.
- **Races (forced order).** `PY -s .claude/prove-it/tools/photo_edit_race.py --repo <checkout> --out <evidence dir> --path P1|P2`
  starts the App through `gated_app.py` and the MCP server, replays the hypothesis path, reads back three ways, and
  writes `transcript.json`, `verdict.txt`, logs and the edit files to `<evidence dir>`.
  - P1: App saves A, clears it, presses restore; the gate stops restore after it read the current and previous edit;
    the agent saves B over MCP (given 1.5 s while the App is stopped); the gate opens. Lost edit = the agent was told
    B was saved but the final edit is not B.
  - P2: no edit; App clears; the gate stops clear after it saw "no edit" (`EditStore.read` → None before the fix,
    `EditStore.exists` → False after); the agent saves A; the gate opens. Lost edit = the agent was told A was saved
    but A is neither the edit nor the previous edit.

## Gotchas

- Since a35545f the edit lock lives at `<data>/edits/edits.lock`; while a request holds it, an agent's save waits up
  to 5 s and then answers conflict 「照片的編輯正被其他程式修改，請稍後再試」. Keep forced pauses under 5 s or the
  agent is refused instead of waiting.
- `previous: true` in an answer only says a `.prev.json` exists; read the file to see which edit it holds.
- The MCP facade is built on the first `tools/call`; warm it before arming a gate or the timing includes the build.
- The gate is per process: it stops the App only; the agent's process runs the checkout's code untouched.

Covers: `darkroom_app/services/photo_library.py`, `darkroom_app/adapters/persist/edit_store.py`,
`darkroom_app/adapters/persist/locks.py`, `darkroom_app/adapters/http/server.py`,
`darkroom_app/adapters/mcp_server/tools.py`, `web/src/requests/edits.ts` — last driven live at e4550aa (and 4afcc58
through a worktree).
