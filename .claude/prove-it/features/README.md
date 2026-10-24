# darkroom feature map

## Baseline preconditions

- A disposable run folder: synthetic presets (`tests/_xmpgen.py`), synthetic photos, an empty `data_dir`, all passed
  with `--preset-dir` / `--data-dir`; never the user's config, presets, photos or `%LOCALAPPDATA%/darkroom`.
- Modules run through `.claude/prove-it/tools/run_module.py --repo <checkout>` (the dedicated Python's `._pth`
  ignores the working directory; see `../recipe.md` § Python).
- Doctor from `../recipe.md` passed for this instance.

## Driving conventions

- HTTP with `X-Darkroom: 1`, JSON bodies, Host `127.0.0.1:<port>`; routes taken from `web/src/requests/*.ts`, the
  same calls the page's buttons make.
- MCP over stdio, another process, warmed with a read-only call before anything is timed.
- Forced order only through `tools/gated_app.py`; say so in the record.

## Proof rules

- Action plus resulting state; a success answer is not the stored result: read it back through the App
  (`GET /api/edit`) and through the CLI (`edit get --json`), and look at the files under `<data>/edits/`.
- A path no entry point reaches is reported unreachable with its missing precondition, never driven through another
  entry point.
- The app's own failure is a finding; product code is never edited to make a drive pass.

## Index

- [photo-edit.md](photo-edit.md) — save, reset to original (clear), restore previous, from the App and from the AI agent.
