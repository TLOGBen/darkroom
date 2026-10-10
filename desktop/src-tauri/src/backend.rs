//! The darkroom backend child process: start it on a free local port, wait until it answers, point the window at
//! it, and make sure it dies with the app.
//!
//! Data flow: `start_backend` (bootstrap page) -> pick a free 127.0.0.1 port -> spawn
//! `python -s -m darkroom_app --port <port>` (the server itself only ever binds 127.0.0.1) -> poll
//! `GET /api/health` until 200 -> navigate the `main` window to `http://127.0.0.1:<port>/`. From then on the window
//! shows the editor page served by Python; the bootstrap page and its IPC permissions are gone (the capability is
//! for the bundled local origin only, so the editor page cannot call these commands).
//!
//! If the child exits before it is healthy, the command fails with its last output lines (e.g. a configuration
//! error) so the bootstrap page can show them verbatim. Output of every run also goes to `logs/backend.log`.

use std::io::Write;
use std::net::{Ipv4Addr, TcpListener};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use tauri::{AppHandle, Manager};
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::TcpStream;
use tokio::process::Child;

use crate::error::CmdError;
use crate::proc::{self, Tail};
use crate::runtime;

/// How long a first start may take before we give up: the first launch warms up the GPU (CUDA kernels compile)
/// and may load torch from a slow disk.
const STARTUP_TIMEOUT: Duration = Duration::from_secs(300);
const POLL_INTERVAL: Duration = Duration::from_millis(300);

/// The running backend, if any. Owned by the app; killed on exit (`stop`).
#[derive(Default)]
pub struct BackendState {
    inner: Mutex<Option<Running>>,
    /// Held for the whole of `start`, so starts never overlap. Without it a page reload during a long first start
    /// (GPU warm-up can take minutes) spawned a second backend that replaced - and so killed - the first, while the
    /// first call kept polling its dead port and, at its timeout, `stop`ped the second one the editor was using.
    /// Now the second call waits for the first and then reuses the backend it started.
    starting: tokio::sync::Mutex<()>,
}

/// A started backend: its process handle (killed on drop / stop) and the port it serves on.
struct Running {
    child: Child,
    port: u16,
}

/// The editor's URL on that port (always the loopback address the server binds to).
fn url_for(port: u16) -> String {
    format!("http://127.0.0.1:{port}/")
}

/// A port nobody listens on right now: bind port 0 on loopback, read what the OS picked, release it.
/// (A tiny race with other programs is possible; the start then fails with the server's own "cannot start" line.)
fn free_port() -> std::io::Result<u16> {
    let listener = TcpListener::bind((Ipv4Addr::LOCALHOST, 0))?;
    Ok(listener.local_addr()?.port())
}

/// One raw `GET /api/health` (no HTTP client crate needed for a single status line). The Host header must be
/// `127.0.0.1:<port>`: the server refuses any other host (DNS-rebinding guard).
async fn healthy(port: u16) -> bool {
    let attempt = async {
        let mut s = TcpStream::connect((Ipv4Addr::LOCALHOST, port)).await?;
        let req = format!(
            "GET /api/health HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nConnection: close\r\n\r\n"
        );
        s.write_all(req.as_bytes()).await?;
        let mut buf = [0u8; 32];
        let n = s.read(&mut buf).await?;
        std::io::Result::Ok(
            buf[..n].starts_with(b"HTTP/1.1 200") || buf[..n].starts_with(b"HTTP/1.0 200"),
        )
    };
    matches!(
        tokio::time::timeout(Duration::from_secs(2), attempt).await,
        Ok(Ok(true))
    )
}

/// Starts the backend (or reuses a live one) and navigates the main window to it. Returns the editor URL.
pub async fn start(app: &AppHandle) -> Result<String, CmdError> {
    let state = app.state::<BackendState>();
    // One start at a time (see `BackendState::starting`); a second caller continues once the first is done.
    let _starting = state.starting.lock().await;

    // A page reload may call this twice: reuse the backend that is already up.
    let existing = {
        let mut guard = state.inner.lock().unwrap_or_else(|e| e.into_inner());
        let alive = guard
            .as_mut()
            .is_some_and(|r| matches!(r.child.try_wait(), Ok(None)));
        if alive {
            guard.as_ref().map(|r| r.port)
        } else {
            *guard = None;
            None
        }
    };
    let port = match existing {
        Some(port) if healthy(port).await => port,
        _ => spawn_and_wait(app, &state).await?,
    };

    let url = url_for(port);
    let window = app
        .get_webview_window("main")
        .ok_or_else(|| CmdError::new("no_window", "main"))?;
    let parsed = tauri::Url::parse(&url).map_err(|e| CmdError::new("io", e.to_string()))?;
    window
        .navigate(parsed)
        .map_err(|e| CmdError::new("io", e.to_string()))?;
    Ok(url)
}

/// Spawns `python -s -m darkroom_app --port <free port>`, records it in `state`, and polls until `/api/health`
/// answers 200 (-> the port), the child exits (-> `backend_exited` with its last lines) or STARTUP_TIMEOUT passes
/// (-> the child is killed, `backend_timeout`). Side effect: (re)creates `logs/backend.log`.
async fn spawn_and_wait(app: &AppHandle, state: &BackendState) -> Result<u16, CmdError> {
    let python = runtime::python_for_backend(app).await?;
    let port = free_port().map_err(|e| CmdError::new("io", e.to_string()))?;

    let mut cmd = proc::command(&python.program);
    cmd.args(["-s", "-m", "darkroom_app", "--port"])
        .arg(port.to_string());
    if let Some(cwd) = &python.cwd {
        cmd.current_dir(cwd);
    }
    let mut child = proc::spawn(&mut cmd).map_err(|e| {
        CmdError::new(
            "python_missing",
            format!("{}: {e}", python.program.display()),
        )
    })?;

    // Keep the last lines for an error message and append everything to logs/backend.log (best effort).
    let tail = Tail::default();
    let log = runtime::layout(app).ok().and_then(|l| {
        let _ = std::fs::create_dir_all(l.log_dir());
        std::fs::File::create(l.log_dir().join("backend.log")).ok()
    });
    let log = Arc::new(Mutex::new(log));
    let sink: Arc<dyn Fn(String) + Send + Sync> = {
        let tail = tail.clone();
        Arc::new(move |line: String| {
            if let Some(f) = log.lock().unwrap_or_else(|e| e.into_inner()).as_mut() {
                let _ = writeln!(f, "{line}");
            }
            tail.push(line);
        })
    };
    proc::pump_child(&mut child, sink);
    *state.inner.lock().unwrap_or_else(|e| e.into_inner()) = Some(Running { child, port });

    let started = Instant::now();
    loop {
        // Did it die (bad configuration, port taken, import error)? Report its own words.
        let exited = {
            let mut guard = state.inner.lock().unwrap_or_else(|e| e.into_inner());
            match guard.as_mut().map(|r| r.child.try_wait()) {
                Some(Ok(Some(status))) => {
                    *guard = None;
                    Some(status.code())
                }
                Some(Ok(None)) => None,
                Some(Err(_)) | None => Some(None),
            }
        };
        if let Some(code) = exited {
            // give the pipe readers a moment to collect the last lines
            tokio::time::sleep(Duration::from_millis(200)).await;
            let code = code.map_or("?".to_string(), |c| c.to_string());
            return Err(CmdError::new(
                "backend_exited",
                format!("exit {code}\n{}", tail.joined()),
            ));
        }
        if healthy(port).await {
            return Ok(port);
        }
        if started.elapsed() > STARTUP_TIMEOUT {
            stop(app);
            return Err(CmdError::new("backend_timeout", tail.joined()));
        }
        tokio::time::sleep(POLL_INTERVAL).await;
    }
}

/// Kills the backend if it runs. Called when the app exits; safe to call any number of times.
pub fn stop(app: &AppHandle) {
    if let Some(state) = app.try_state::<BackendState>()
        && let Some(mut running) = state.inner.lock().unwrap_or_else(|e| e.into_inner()).take()
    {
        // TerminateProcess on Windows / SIGKILL elsewhere. darkroom writes every file atomically
        // (temp file + rename), so an abrupt stop never leaves a half-written edit or index behind.
        let _ = running.child.start_kill();
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn free_port_is_nonzero_and_url_is_loopback() {
        let port = free_port().unwrap();
        assert_ne!(port, 0);
        assert_eq!(url_for(port), format!("http://127.0.0.1:{port}/"));
    }

    #[test]
    fn health_check_fails_fast_on_a_closed_port() {
        let port = free_port().unwrap();
        let rt = tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()
            .unwrap();
        assert!(!rt.block_on(healthy(port)));
    }
}
