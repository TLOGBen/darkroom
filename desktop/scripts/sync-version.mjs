#!/usr/bin/env node
// Copies darkroom's single version (darkroom_app/__init__.py `__version__`, plan-v2 §0) into the desktop files that
// need it as a literal: desktop/src-tauri/tauri.conf.json ("version") and the [package] version of
// desktop/src-tauri/Cargo.toml and desktop/cli/Cargo.toml. pyproject.toml needs nothing: hatch reads __init__.py.
//
//   node desktop/scripts/sync-version.mjs           write the files (prints what changed)
//   node desktop/scripts/sync-version.mjs --check   change nothing; exit 1 if any file is out of sync (CI)
//
// Plain Node, no packages: it runs before `npm ci` in CI and anywhere node exists. Edits are textual (one line
// each), so comments and formatting in the files stay exactly as they were. Cargo.lock catches up on the next
// cargo command.
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const repo = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const check = process.argv.includes("--check");

const init = readFileSync(join(repo, "darkroom_app", "__init__.py"), "utf8");
const found = init.match(/^__version__\s*=\s*["']([^"']+)["']/m);
if (!found) {
  console.error("sync-version: __version__ not found in darkroom_app/__init__.py");
  process.exit(2);
}
const version = found[1];
// MSI (WiX) needs a numeric major.minor.patch; refuse anything else up front instead of failing deep in the bundler.
if (!/^\d+\.\d+\.\d+$/.test(version)) {
  console.error(`sync-version: __version__ "${version}" must be MAJOR.MINOR.PATCH (digits only) for the installers`);
  process.exit(2);
}

/** Each target: a file and a regex whose group 1 is the text before the version and group 2 the version. */
const targets = [
  // the top-level "version" key (the only one at two-space indent in this file)
  { file: join(repo, "desktop", "src-tauri", "tauri.conf.json"), re: /^(  "version":\s*")([^"]*)"/m },
  // the first `version = "..."` line, which is the [package] one (dependencies use inline tables)
  { file: join(repo, "desktop", "src-tauri", "Cargo.toml"), re: /^(version\s*=\s*")([^"]*)"/m },
  { file: join(repo, "desktop", "cli", "Cargo.toml"), re: /^(version\s*=\s*")([^"]*)"/m },
];

let stale = 0;
for (const { file, re } of targets) {
  const name = relative(repo, file).replaceAll("\\", "/");
  const text = readFileSync(file, "utf8");
  const m = text.match(re);
  if (!m) {
    console.error(`sync-version: no version field found in ${name}`);
    process.exit(2);
  }
  if (m[2] === version) {
    console.log(`${name}: ${version} (ok)`);
    continue;
  }
  stale += 1;
  if (check) {
    console.error(`${name}: ${m[2]} != ${version}`);
  } else {
    writeFileSync(file, text.replace(re, `$1${version}"`));
    console.log(`${name}: ${m[2]} -> ${version}`);
  }
}
if (check && stale) {
  console.error("sync-version: out of sync; run `node desktop/scripts/sync-version.mjs`");
  process.exit(1);
}
