//! Child processes: one place that decides how darkroom starts `uv` and Python.
//!
//! Every child gets: no stdin, stdout and stderr piped back to us (shown on the bootstrap page or kept for the error
//! message), `kill_on_drop` (a child never outlives the handle that owns it), and on Windows `CREATE_NO_WINDOW` so a
//! GUI app does not flash console windows. Started through `spawn`, it also dies with this process however this
//! process ends - crash and forced kill included (`killjob`: a Windows Job Object, Linux `PR_SET_PDEATHSIG`).

use std::collections::VecDeque;
use std::ffi::OsStr;
use std::process::Stdio;
use std::sync::{Arc, Mutex};

use tokio::io::{AsyncBufReadExt, AsyncRead, BufReader};
use tokio::process::{Child, Command};
use tokio::sync::watch;

/// How many trailing output lines are kept for an error message.
const TAIL_LINES: usize = 40;

/// A `Command` with darkroom's child-process defaults (see the module docs).
pub fn command(program: impl AsRef<OsStr>) -> Command {
    let mut cmd = Command::new(program);
    cmd.stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .kill_on_drop(true)
        // Python prints UTF-8 whatever the console code page is, so lines decode the same everywhere.
        .env("PYTHONUTF8", "1")
        .env("PYTHONIOENCODING", "utf-8");
    #[cfg(windows)]
    cmd.creation_flags(0x0800_0000); // CREATE_NO_WINDOW
    #[cfg(target_os = "linux")]
    // SAFETY: the closure only calls prctl, which is async-signal-safe (allowed between fork and exec).
    unsafe {
        cmd.pre_exec(crate::killjob::die_with_parent);
    }
    cmd
}

/// Spawns `cmd` and, on Windows, puts the child into this process's kill-on-close job (`killjob::adopt`), so it is
/// killed when this process ends for any reason. Every long-running child (the backend, uv) is started here.
pub fn spawn(cmd: &mut Command) -> std::io::Result<Child> {
    let child = cmd.spawn()?;
    #[cfg(windows)]
    if let Some(handle) = child.raw_handle() {
        crate::killjob::adopt(handle);
    }
    Ok(child)
}

/// The last `TAIL_LINES` lines a child printed (stdout and stderr interleaved in arrival order).
#[derive(Clone, Default)]
pub struct Tail(Arc<Mutex<VecDeque<String>>>);

impl Tail {
    /// Appends one line, dropping the oldest when TAIL_LINES are already kept. A poisoned lock is recovered
    /// (losing a log line is better than panicking the pipe reader).
    pub fn push(&self, line: String) {
        let mut q = self.0.lock().unwrap_or_else(|e| e.into_inner());
        if q.len() == TAIL_LINES {
            q.pop_front();
        }
        q.push_back(line);
    }

    /// The kept lines joined with `\n` (for an error's `detail`).
    pub fn joined(&self) -> String {
        let q = self.0.lock().unwrap_or_else(|e| e.into_inner());
        q.iter().cloned().collect::<Vec<_>>().join("\n")
    }
}

/// Reads one pipe line by line (lossy UTF-8, so a stray byte never stops the reader and blocks the child) and hands
/// every non-empty line to `sink`. Ends when the child closes the pipe.
pub fn pump<R>(
    reader: R,
    sink: Arc<dyn Fn(String) + Send + Sync>,
) -> tauri::async_runtime::JoinHandle<()>
where
    R: AsyncRead + Unpin + Send + 'static,
{
    tauri::async_runtime::spawn(async move {
        let mut reader = BufReader::new(reader);
        let mut buf = Vec::new();
        loop {
            buf.clear();
            match reader.read_until(b'\n', &mut buf).await {
                Ok(0) | Err(_) => break,
                Ok(_) => {
                    let line = String::from_utf8_lossy(&buf).trim_end().to_string();
                    if !line.is_empty() {
                        sink(line);
                    }
                }
            }
        }
    })
}

/// Starts pumping both pipes of `child` into `sink`.
pub fn pump_child(
    child: &mut Child,
    sink: Arc<dyn Fn(String) + Send + Sync>,
) -> Vec<tauri::async_runtime::JoinHandle<()>> {
    let mut handles = Vec::new();
    if let Some(out) = child.stdout.take() {
        handles.push(pump(out, sink.clone()));
    }
    if let Some(err) = child.stderr.take() {
        handles.push(pump(err, sink));
    }
    handles
}

/// How a streamed run ended.
pub enum RunOutcome {
    /// The child exited on its own; `tail` holds its last output lines.
    Exited {
        success: bool,
        code: Option<i32>,
        tail: String,
    },
    /// `cancel` flipped to true while it ran; the child was killed.
    Cancelled,
}

/// Runs `cmd` to completion, sending each output line to `on_line`, and kills it as soon as `cancel` becomes true.
pub async fn run_streaming(
    mut cmd: Command,
    mut cancel: watch::Receiver<bool>,
    on_line: Arc<dyn Fn(String) + Send + Sync>,
) -> std::io::Result<RunOutcome> {
    if *cancel.borrow() {
        return Ok(RunOutcome::Cancelled);
    }
    let mut child = spawn(&mut cmd)?;
    let tail = Tail::default();
    let sink: Arc<dyn Fn(String) + Send + Sync> = {
        let tail = tail.clone();
        Arc::new(move |line: String| {
            tail.push(line.clone());
            on_line(line);
        })
    };
    let pumps = pump_child(&mut child, sink);
    // Resolves only when cancel flips to true (a dropped sender means "never cancelled", not "cancel now").
    // The watch guard is dropped inside this block, so nothing non-Send is held across the awaits below.
    let cancelled = async {
        if cancel.wait_for(|c| *c).await.is_err() {
            std::future::pending::<()>().await;
        }
    };
    let status = tokio::select! {
        status = child.wait() => Some(status?),
        () = cancelled => None,
    };
    let Some(status) = status else {
        let _ = child.kill().await;
        return Ok(RunOutcome::Cancelled);
    };
    // Drain whatever the child printed right before exiting, so the error message is complete.
    for p in pumps {
        let _ = p.await;
    }
    Ok(RunOutcome::Exited {
        success: status.success(),
        code: status.code(),
        tail: tail.joined(),
    })
}
