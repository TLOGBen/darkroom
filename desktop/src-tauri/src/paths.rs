//! Where the managed Python environment lives, and how to find the tools that build it.
//!
//! Layout under the app's local data folder (`<app_local_data_dir>` = `%LOCALAPPDATA%\<identifier>` on Windows,
//! `$XDG_DATA_HOME/<identifier>` or `~/.local/share/<identifier>` on Linux):
//!
//! ```text
//! <app_local_data_dir>/
//!   runtime/                  the virtual environment (Scripts/python.exe or bin/python) - plan-v2 §4 `<app data>/runtime/`
//!     darkroom-runtime.json   written last, only after every install step succeeded (see `Marker`)
//!   uv/python/                the Python interpreter uv downloads (python-build-standalone); the venv points here
//!   uv/cache/                 uv's download / wheel cache, so a cancelled install resumes without re-downloading
//!   logs/backend.log          stdout+stderr of the last backend run
//! ```
//!
//! Keeping uv's interpreter and cache next to the environment (instead of uv's global defaults) means removing the
//! one app folder removes everything darkroom downloaded. The `darkroom` CLI launcher (desktop/cli) finds the same
//! `runtime/` with the same rule; a test there checks that both agree on the identifier.

use std::path::{Path, PathBuf};

/// Python minor version the environment is created with (darkroom targets 3.13).
pub const PYTHON_VERSION: &str = "3.13";
/// torch build installed next to darkroom (same pin as requirements.txt's install note).
pub const TORCH_VERSION: &str = "2.14.0";
/// Written into `runtime/` after a complete install; its absence means "not ready".
pub const MARKER_FILE: &str = "darkroom-runtime.json";

/// Paths of the managed environment, rooted at the app's local data folder.
#[derive(Debug, Clone)]
pub struct Layout {
    root: PathBuf,
}

impl Layout {
    /// A layout rooted at `root` (the app's local data folder). Nothing is created on disk.
    pub fn new(root: PathBuf) -> Self {
        Self { root }
    }

    /// The app's local data folder itself.
    pub fn root(&self) -> &Path {
        &self.root
    }

    /// `<root>/runtime`: the virtual environment darkroom runs in.
    pub fn runtime_dir(&self) -> PathBuf {
        self.root.join("runtime")
    }

    /// The environment's interpreter (it may not exist yet).
    pub fn python(&self) -> PathBuf {
        python_in(&self.runtime_dir())
    }

    /// `<root>/runtime/darkroom-runtime.json`: present only after a complete install.
    pub fn marker(&self) -> PathBuf {
        self.runtime_dir().join(MARKER_FILE)
    }

    /// `<root>/uv/python`: where uv keeps the standalone CPython the venv is built on.
    pub fn uv_python_dir(&self) -> PathBuf {
        self.root.join("uv").join("python")
    }

    /// `<root>/uv/cache`: uv's download cache (lets a cancelled install resume).
    pub fn uv_cache_dir(&self) -> PathBuf {
        self.root.join("uv").join("cache")
    }

    /// `<root>/logs`: the backend's output log.
    pub fn log_dir(&self) -> PathBuf {
        self.root.join("logs")
    }
}

/// The interpreter inside a virtual environment (venv layout differs between Windows and POSIX).
pub fn python_in(venv: &Path) -> PathBuf {
    if cfg!(windows) {
        venv.join("Scripts").join("python.exe")
    } else {
        venv.join("bin").join("python")
    }
}

/// The `uv` used to build the environment, first match wins:
/// 1. `DARKROOM_UV` (explicit override, handy when developing);
/// 2. the sidecar the installer put next to this executable (`bundle.externalBin` strips the target triple, so it is
///    plain `uv` / `uv.exe` beside `darkroom-desktop`);
/// 3. `uv` on PATH (local development with `cargo run` / `tauri dev`, where no sidecar was copied).
pub fn find_uv() -> PathBuf {
    if let Some(p) = std::env::var_os("DARKROOM_UV").filter(|v| !v.is_empty()) {
        return PathBuf::from(p);
    }
    let exe_name = if cfg!(windows) { "uv.exe" } else { "uv" };
    if let Some(dir) = std::env::current_exe()
        .ok()
        .and_then(|p| p.parent().map(Path::to_path_buf))
    {
        let sidecar = dir.join(exe_name);
        if sidecar.is_file() {
            return sidecar;
        }
    }
    PathBuf::from(exe_name)
}

/// A `file://` URL for a local path, as needed by a PEP 508 direct reference (`darkroom[heic] @ file:///...`).
///
/// Backslashes become slashes, a Windows verbatim prefix (`\\?\`, which `canonicalize` adds) is dropped, and every
/// byte outside the unreserved set (plus `/` and the drive colon) is percent-encoded, so user folders with spaces or
/// non-ASCII names still form a valid URL.
pub fn file_url(path: &Path) -> String {
    let raw = path.to_string_lossy().replace('\\', "/");
    let raw = raw.strip_prefix("//?/").unwrap_or(&raw);
    let mut out = String::from(if raw.starts_with('/') {
        "file://"
    } else {
        "file:///"
    });
    for b in raw.bytes() {
        match b {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'.' | b'_' | b'~' | b'/' | b':' => {
                out.push(b as char)
            }
            _ => out.push_str(&format!("%{b:02X}")),
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn file_url_encodes_spaces_and_windows_prefix() {
        assert_eq!(
            file_url(Path::new(
                r"\\?\C:\Users\A B\darkroom-0.1.0-py3-none-any.whl"
            )),
            "file:///C:/Users/A%20B/darkroom-0.1.0-py3-none-any.whl"
        );
        assert_eq!(
            file_url(Path::new("/home/a/相片/x.whl")),
            "file:///home/a/%E7%9B%B8%E7%89%87/x.whl"
        );
    }

    #[test]
    fn layout_paths_live_under_the_root() {
        let l = Layout::new(PathBuf::from("root"));
        assert!(l.python().starts_with(l.runtime_dir()));
        assert!(l.marker().ends_with(MARKER_FILE));
        assert!(l.uv_cache_dir().starts_with(l.root()));
    }
}
