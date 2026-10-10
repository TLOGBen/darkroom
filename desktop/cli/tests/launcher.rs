//! End-to-end checks of the built `darkroom` executable (no real darkroom environment needed).

use std::process::Command;

fn launcher() -> Command {
    let mut cmd = Command::new(env!("CARGO_BIN_EXE_darkroom"));
    // Never pick up the developer's real environment.
    cmd.env_remove("DARKROOM_PYTHON");
    let empty = std::env::temp_dir().join("darkroom-cli-it-empty");
    for key in ["LOCALAPPDATA", "XDG_DATA_HOME", "HOME"] {
        cmd.env(key, &empty);
    }
    cmd
}

#[test]
fn version_prints_the_crate_version() {
    let out = launcher().arg("--version").output().unwrap();
    assert!(out.status.success());
    assert_eq!(
        String::from_utf8_lossy(&out.stdout).trim(),
        format!("darkroom {}", env!("CARGO_PKG_VERSION"))
    );
}

#[test]
fn no_environment_exits_5_with_a_bilingual_line() {
    let out = launcher()
        .args(["capabilities", "--json"])
        .output()
        .unwrap();
    assert_eq!(out.status.code(), Some(5));
    let err = String::from_utf8_lossy(&out.stderr);
    assert!(err.contains("找不到 darkroom 的 Python 環境"), "{err}");
    assert!(err.contains("Python environment not found"), "{err}");
    assert_eq!(err.trim_end().lines().count(), 1, "{err}");
    assert!(out.stdout.is_empty());
}

#[test]
fn a_missing_darkroom_python_also_exits_5() {
    let out = launcher()
        .env(
            "DARKROOM_PYTHON",
            std::env::temp_dir()
                .join("darkroom-no-such-python")
                .join("python"),
        )
        .arg("capabilities")
        .output()
        .unwrap();
    assert_eq!(out.status.code(), Some(5));
}

/// stdin, stdout and the exit code pass straight through: `/bin/sh -s` reads its script from stdin and gets the
/// module name as `$1` (`-m` before it is just sh's job-control flag).
#[cfg(unix)]
#[test]
fn stdio_and_exit_code_pass_through() {
    use std::io::Write;
    use std::process::Stdio;
    let mut child = launcher()
        .env("DARKROOM_PYTHON", "/bin/sh")
        .args(["presets", "list"])
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
        .unwrap();
    child
        .stdin
        .take()
        .unwrap()
        .write_all(b"echo \"$1 $2 $3\"; exit 7\n")
        .unwrap();
    let out = child.wait_with_output().unwrap();
    assert_eq!(out.status.code(), Some(7));
    assert_eq!(
        String::from_utf8_lossy(&out.stdout).trim(),
        "darkroom_app.cli presets list"
    );
}
