//! The error every command returns to the bootstrap page.
//!
//! `code` is a fixed word the page translates (zh-TW / en-US); `detail` is the raw technical text (a path, uv's last
//! output lines, an OS error) shown verbatim under the translated sentence, so nothing is guessed or hidden.

use serde::Serialize;

/// Serialised to the page as `{"code": ..., "detail": ...}` (Tauri rejects the command's promise with it).
#[derive(Debug, Clone, Serialize)]
pub struct CmdError {
    /// `busy` | `cancelled` | `uv_missing` | `wheel_missing` | `step_failed` | `io` | `python_missing` |
    /// `backend_exited` | `backend_timeout` | `no_window` | `settings_refused` (the backend's sentence in `detail`)
    pub code: &'static str,
    /// Untranslated technical detail, shown as-is under the translated sentence (may be empty).
    pub detail: String,
}

impl CmdError {
    /// An error with one of the fixed codes listed on `code` and its raw detail text.
    pub fn new(code: &'static str, detail: impl Into<String>) -> Self {
        Self {
            code,
            detail: detail.into(),
        }
    }
}
