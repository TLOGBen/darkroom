//! `darkroom` - the command-line launcher (plan-v2 §4).
//!
//! The real CLI, MCP server and App are Python (`darkroom_app`). This tiny executable only finds the Python
//! environment the desktop app installed and runs the right module in it, passing everything through untouched:
//!
//! ```text
//! darkroom <args...>        ->  python -s -m darkroom_app.cli <args...>
//! darkroom mcp <args...>    ->  python -s -m darkroom_app.mcp_server <args...>
//! darkroom app <args...>    ->  python -s -m darkroom_app <args...>
//! darkroom --version        ->  prints this launcher's version (kept equal to darkroom_app.__version__ by CI)
//! ```
//!
//! stdin / stdout / stderr are inherited (so `--json` output, JPEG bytes on stdout and MCP's stdio JSON-RPC all flow
//! straight through) and the child's exit code becomes ours (0 / 1 / 2 / 3 / 4 / 5 / 6 keep their meaning).
//!
//! On Windows the launcher waits for Python instead of replacing itself, so the child is put into a kill-on-close
//! Job Object (`killjob`): when the launcher ends - however it ends - Python ends with it.
//!
//! Which Python: `DARKROOM_PYTHON` if set (any interpreter that can `import darkroom_app`), otherwise the managed
//! environment `<local app data>/<identifier>/runtime/` that the desktop app's first-run setup created - the same
//! folder rule as the Tauri shell (`app_local_data_dir`). When neither exists the launcher prints one line in
//! Chinese and English and exits 5 (`unavailable`, the same code the Python CLI uses for "cannot be used right now").

use std::ffi::OsString;
use std::path::{Path, PathBuf};
use std::process::Command;

/// Tauri bundle identifier of the desktop app; its local data folder holds `runtime/`. A test checks it against
/// desktop/src-tauri/tauri.conf.json so the two can never drift apart.
const IDENTIFIER: &str = "io.github.tlogben.darkroom";
/// Written by the desktop app after a complete install (desktop/src-tauri/src/paths.rs `MARKER_FILE`).
const MARKER_FILE: &str = "darkroom-runtime.json";
/// Exit code when no usable environment exists (`unavailable`, AGENTS.md exit-code table).
const EXIT_UNAVAILABLE: i32 = 5;

/// What one invocation does.
#[derive(Debug, PartialEq)]
enum Plan {
    /// Print the launcher's own version and exit 0 (no Python needed).
    Version,
    /// Run `python -s -m <module> <args...>` in the managed (or overridden) environment.
    Run {
        module: &'static str,
        args: Vec<OsString>,
    },
}

/// Maps the launcher's arguments to a Python module and its arguments. Only the first argument is looked at;
/// everything else is passed on byte for byte.
fn plan(args: Vec<OsString>) -> Plan {
    let first = args.first().and_then(|a| a.to_str());
    match first {
        Some("--version") | Some("-V") => Plan::Version,
        Some("mcp") => Plan::Run {
            module: "darkroom_app.mcp_server",
            args: args[1..].to_vec(),
        },
        Some("app") => Plan::Run {
            module: "darkroom_app",
            args: args[1..].to_vec(),
        },
        _ => Plan::Run {
            module: "darkroom_app.cli",
            args,
        },
    }
}

/// The platform's per-user local data folder, matching Tauri's `app_local_data_dir` base (the `dirs` crate rule):
/// Windows `%LOCALAPPDATA%`, macOS `~/Library/Application Support`, Linux `$XDG_DATA_HOME` (when absolute) or
/// `~/.local/share`.
fn local_data_dir(env: &dyn Fn(&str) -> Option<OsString>) -> Option<PathBuf> {
    let non_empty = |k: &str| env(k).filter(|v| !v.is_empty()).map(PathBuf::from);
    if cfg!(windows) {
        non_empty("LOCALAPPDATA")
    } else if cfg!(target_os = "macos") {
        non_empty("HOME").map(|h| h.join("Library").join("Application Support"))
    } else {
        non_empty("XDG_DATA_HOME")
            .filter(|p| p.is_absolute())
            .or_else(|| non_empty("HOME").map(|h| h.join(".local").join("share")))
    }
}

/// The interpreter inside the managed venv.
fn managed_python(runtime: &Path) -> PathBuf {
    if cfg!(windows) {
        runtime.join("Scripts").join("python.exe")
    } else {
        runtime.join("bin").join("python")
    }
}

/// Where the interpreter comes from, or why there is none (the text after the colon in the error line).
fn find_python(env: &dyn Fn(&str) -> Option<OsString>) -> Result<PathBuf, String> {
    if let Some(p) = env("DARKROOM_PYTHON").filter(|v| !v.is_empty()) {
        // A bare command name (e.g. `python3`) is resolved through PATH by the OS when spawned.
        return Ok(PathBuf::from(p));
    }
    let base = local_data_dir(env).ok_or_else(|| "no local app data folder".to_string())?;
    let runtime = base.join(IDENTIFIER).join("runtime");
    let python = managed_python(&runtime);
    if python.is_file() && runtime.join(MARKER_FILE).is_file() {
        Ok(python)
    } else {
        Err(runtime.display().to_string())
    }
}

/// Prints the bilingual "environment not found" line to stderr and exits 5 (`unavailable`).
fn not_found(detail: &str) -> ! {
    eprintln!(
        "darkroom：找不到 darkroom 的 Python 環境（{detail}）；請先開啟 darkroom App 完成第一次設定，或用環境變數 \
         DARKROOM_PYTHON 指定直譯器。 / darkroom: Python environment not found ({detail}); open the darkroom app once \
         to finish setup, or set DARKROOM_PYTHON."
    );
    std::process::exit(EXIT_UNAVAILABLE);
}

// Windows: the Python child joins a kill-on-close Job Object, so stopping the launcher (Stop-Process, an MCP client
// that kills only the process it started, closing the console) also stops Python - no orphan keeps the App's port.
// The same file the desktop shell uses (std only, so the launcher stays dependency-free).
#[cfg(windows)]
#[path = "../../src-tauri/src/killjob.rs"]
mod killjob;

#[cfg(windows)]
mod console {
    //! Ctrl+C in a console reaches every process attached to it. The Python child handles it (and exits with its
    //! own code); the launcher must just keep waiting so it can return that code. A handler that swallows the event
    //! does that without being inherited (unlike `SetConsoleCtrlHandler(NULL, TRUE)`, which the child would inherit
    //! and then ignore Ctrl+C too).
    type Handler = unsafe extern "system" fn(u32) -> i32;

    #[link(name = "kernel32")]
    unsafe extern "system" {
        fn SetConsoleCtrlHandler(handler: Option<Handler>, add: i32) -> i32;
    }

    unsafe extern "system" fn swallow(_ctrl_type: u32) -> i32 {
        1
    }

    /// Installs the swallowing Ctrl+C handler for this (launcher) process only.
    pub fn let_child_handle_ctrl_c() {
        // SAFETY: registers a handler with the documented signature that touches no state.
        unsafe {
            SetConsoleCtrlHandler(Some(swallow), 1);
        }
    }
}

/// Runs the module and never returns: on Unix by `exec` (the launcher becomes Python), elsewhere by waiting for the
/// child and exiting with its code. `-s` keeps the user's site-packages out, as everywhere in darkroom.
fn run(python: &Path, module: &str, args: Vec<OsString>) -> ! {
    let mut cmd = Command::new(python);
    cmd.arg("-s").arg("-m").arg(module).args(args);

    #[cfg(unix)]
    {
        // Replace this process: signals, stdio and the exit status are the child's own, with nothing in between.
        use std::os::unix::process::CommandExt;
        let err = cmd.exec();
        not_found(&format!("{}: {err}", python.display()));
    }

    #[cfg(not(unix))]
    {
        #[cfg(windows)]
        console::let_child_handle_ctrl_c();
        let mut child = match cmd.spawn() {
            Ok(child) => child,
            Err(err) => not_found(&format!("{}: {err}", python.display())),
        };
        #[cfg(windows)]
        {
            use std::os::windows::io::AsRawHandle;
            killjob::adopt(child.as_raw_handle());
        }
        match child.wait() {
            Ok(status) => std::process::exit(status.code().unwrap_or(1)),
            Err(err) => not_found(&format!("{}: {err}", python.display())),
        }
    }
}

/// Entry point: plan from the arguments, then print the version or hand over to Python.
fn main() {
    let args: Vec<OsString> = std::env::args_os().skip(1).collect();
    match plan(args) {
        Plan::Version => println!("darkroom {}", env!("CARGO_PKG_VERSION")),
        Plan::Run { module, args } => {
            let env = |k: &str| std::env::var_os(k);
            match find_python(&env) {
                Ok(python) => run(&python, module, args),
                Err(detail) => not_found(&detail),
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn os(v: &[&str]) -> Vec<OsString> {
        v.iter().map(OsString::from).collect()
    }

    #[test]
    fn routes_subcommands_to_modules() {
        assert_eq!(plan(os(&["--version"])), Plan::Version);
        assert_eq!(
            plan(os(&["mcp"])),
            Plan::Run {
                module: "darkroom_app.mcp_server",
                args: vec![]
            }
        );
        assert_eq!(
            plan(os(&["app", "--port", "8799"])),
            Plan::Run {
                module: "darkroom_app",
                args: os(&["--port", "8799"])
            }
        );
        assert_eq!(
            plan(os(&["presets", "list", "--json"])),
            Plan::Run {
                module: "darkroom_app.cli",
                args: os(&["presets", "list", "--json"])
            }
        );
        assert_eq!(
            plan(vec![]),
            Plan::Run {
                module: "darkroom_app.cli",
                args: vec![]
            }
        );
    }

    #[test]
    fn darkroom_python_wins() {
        let env = |k: &str| (k == "DARKROOM_PYTHON").then(|| OsString::from("/opt/py/bin/python"));
        assert_eq!(
            find_python(&env).unwrap(),
            PathBuf::from("/opt/py/bin/python")
        );
    }

    #[test]
    fn missing_managed_env_names_the_folder() {
        let tmp = std::env::temp_dir().join("darkroom-cli-test-empty");
        let tmp_os = tmp.clone().into_os_string();
        let env = move |k: &str| {
            matches!(k, "LOCALAPPDATA" | "HOME" | "XDG_DATA_HOME").then(|| tmp_os.clone())
        };
        let err = find_python(&env).unwrap_err();
        assert!(err.contains(IDENTIFIER), "{err}");
    }

    #[test]
    fn identifier_and_version_match_the_tauri_config() {
        let conf = include_str!("../../src-tauri/tauri.conf.json");
        assert!(
            conf.contains(&format!("\"identifier\": \"{IDENTIFIER}\"")),
            "identifier drifted from tauri.conf.json"
        );
        assert!(
            conf.contains(&format!("\"version\": \"{}\"", env!("CARGO_PKG_VERSION"))),
            "version drifted: run `node desktop/scripts/sync-version.mjs`"
        );
    }

    #[test]
    fn marker_name_matches_the_desktop_app() {
        let paths = include_str!("../../src-tauri/src/paths.rs");
        assert!(paths.contains(&format!("MARKER_FILE: &str = \"{MARKER_FILE}\"")));
    }
}
