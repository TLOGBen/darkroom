//! First-run settings the bootstrap page asks for before the backend can start: the preset folder.
//!
//! Why here: `python -s -m darkroom_app` exits (code 2) when no preset folder is configured, and an installed copy
//! of darkroom has no `config.local.json` to hand-edit and does not ship the `darkroom` CLI. So, once the runtime is
//! ready and before `start_backend`, the page asks `preset_setup_status`; when no usable preset folder is
//! configured it lets the user pick one (the dialog plugin's folder picker) and calls `set_preset_dir`.
//!
//! Data flow: both commands run the managed Python's own CLI - `python -s -m darkroom_app.cli settings get --json`
//! / `settings set preset_dir=<folder> --json` - so the settings file, its location (DARKROOM_CONFIG ->
//! config.local.json in a checkout -> the platform's settings file), and every check (the folder must exist, a key
//! is never written...) are exactly the backend's; nothing here writes a file itself. The CLI's one-line JSON
//! envelope is parsed; a refusal comes back as `settings_refused` with the backend's sentence verbatim.

use std::path::Path;

use serde::Serialize;
use serde_json::Value;
use tauri::AppHandle;

use crate::error::CmdError;
use crate::proc;
use crate::runtime;

/// What the page needs to decide whether to ask for a preset folder.
#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct PresetSetup {
    /// A preset folder is configured and exists: the backend can start.
    pub configured: bool,
    /// The configured preset folder (from preset_dir, or derived from localllms_root), if any.
    pub preset_dir: Option<String>,
    /// The settings file the backend reads and writes (shown to the user).
    pub config_file: Option<String>,
}

/// Runs `python -s -m darkroom_app.cli <args> --json` in the backend's interpreter and returns `result`; a refusal
/// (`ok: false`) is `settings_refused` with the CLI's message; anything unparsable is `io` with the raw output.
async fn run_cli(app: &AppHandle, args: &[&str]) -> Result<Value, CmdError> {
    let python = runtime::python_for_backend(app).await?;
    let mut cmd = proc::command(&python.program);
    cmd.args(["-s", "-m", "darkroom_app.cli"])
        .args(args)
        .arg("--json");
    if let Some(cwd) = &python.cwd {
        cmd.current_dir(cwd);
    }
    let out = cmd.output().await.map_err(|e| {
        CmdError::new(
            "python_missing",
            format!("{}: {e}", python.program.display()),
        )
    })?;
    let stdout = String::from_utf8_lossy(&out.stdout);
    envelope(&stdout).map_err(|err| match err {
        Envelope::Refused(message) => CmdError::new("settings_refused", message),
        Envelope::Garbled => CmdError::new(
            "io",
            format!(
                "{}\n{}",
                stdout.trim(),
                String::from_utf8_lossy(&out.stderr).trim()
            ),
        ),
    })
}

/// Why the CLI's stdout was not a success envelope.
#[derive(Debug, PartialEq)]
enum Envelope {
    /// `{"ok": false, "error": {"message": ...}}`
    Refused(String),
    /// Not the one-line JSON envelope at all.
    Garbled,
}

/// The `result` of the CLI's `--json` envelope (its first line).
fn envelope(stdout: &str) -> Result<Value, Envelope> {
    let line = stdout.lines().next().unwrap_or("");
    let v: Value = serde_json::from_str(line).map_err(|_| Envelope::Garbled)?;
    if v.get("ok") == Some(&Value::Bool(true)) {
        return Ok(v.get("result").cloned().unwrap_or(Value::Null));
    }
    match v.pointer("/error/message").and_then(Value::as_str) {
        Some(message) => Err(Envelope::Refused(message.to_string())),
        None => Err(Envelope::Garbled),
    }
}

/// `settings get` / `settings set` result -> what the page needs; `is_dir` is replaceable for tests.
fn setup_from(result: &Value, is_dir: impl Fn(&Path) -> bool) -> PresetSetup {
    let text = |p: &str| {
        result
            .pointer(p)
            .and_then(Value::as_str)
            .map(str::to_string)
    };
    let preset_dir = text("/settings/preset_dir");
    PresetSetup {
        configured: preset_dir.as_deref().is_some_and(|d| is_dir(Path::new(d))),
        preset_dir,
        config_file: text("/config_file"),
    }
}

/// Is a usable preset folder configured? Reads only.
pub async fn status(app: &AppHandle) -> Result<PresetSetup, CmdError> {
    let got = run_cli(app, &["settings", "get"]).await?;
    Ok(setup_from(&got, Path::is_dir))
}

/// Writes `preset_dir` through the backend's own `settings set` (all its checks apply), then reports again.
pub async fn set_preset_dir(app: &AppHandle, path: &str) -> Result<PresetSetup, CmdError> {
    if path.trim().is_empty() {
        return Err(CmdError::new("settings_refused", "preset_dir"));
    }
    let arg = format!("preset_dir={}", path.trim());
    run_cli(app, &["settings", "set", &arg]).await?;
    status(app).await
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn reads_the_cli_envelope() {
        let ok =
            r#"{"ok":true,"result":{"settings":{"preset_dir":"D:/p"},"config_file":"C:/c.json"}}"#;
        assert_eq!(
            envelope(ok).unwrap().pointer("/settings/preset_dir"),
            Some(&Value::from("D:/p"))
        );
        let refused = r#"{"ok":false,"error":{"kind":"invalid","message":"preset_dir 指定的資料夾不存在：X"}}"#;
        assert_eq!(
            envelope(refused),
            Err(Envelope::Refused("preset_dir 指定的資料夾不存在：X".into()))
        );
        assert_eq!(envelope("Traceback ..."), Err(Envelope::Garbled));
        assert_eq!(envelope(""), Err(Envelope::Garbled));
    }

    #[test]
    fn configured_only_when_the_folder_exists() {
        let got: Value =
            serde_json::from_str(r#"{"settings":{"preset_dir":"D:/p"},"config_file":"C:/c.json"}"#)
                .unwrap();
        let yes = setup_from(&got, |_| true);
        assert!(yes.configured);
        assert_eq!(yes.config_file.as_deref(), Some("C:/c.json"));
        assert!(!setup_from(&got, |_| false).configured);
        let none: Value = serde_json::from_str(r#"{"settings":{"preset_dir":null}}"#).unwrap();
        let s = setup_from(&none, |_| true);
        assert!(!s.configured);
        assert_eq!(s.preset_dir, None);
    }
}
