//! The managed Python environment: is it ready, and building it (only after the user agreed on the bootstrap page).
//!
//! Install flow (each step is a `uv` run whose output lines stream to the page as `setup-progress` events):
//! 1. `python`   - `uv venv --python 3.13 <runtime>`; uv downloads a standalone CPython into `uv/python/`.
//!    Skipped when `runtime/` already has an interpreter (a cancelled or older install is resumed, not redone).
//! 2. `torch`    - `uv pip install torch==<pin>` from PyTorch's own index: CUDA 13.0 on Windows/Linux when
//!    `nvidia-smi` sees a GPU, the CPU index otherwise. torch never ships inside the installer (GitHub Releases'
//!    2 GB per-file cap and the CUDA build alone is ~2.5 GB; plan-v2 §4).
//! 3. `darkroom` - `uv pip install "darkroom[heic,semantic] @ file:///<bundled wheel>"`, reinstalling darkroom even
//!    when the version is unchanged so a rebuilt wheel always lands.
//! 4. write `runtime/darkroom-runtime.json` (the marker). Only a marker matching this app's version and the torch pin
//!    counts as ready, so an app update re-runs steps 2-3 (uv skips what is already satisfied) on the next start.
//!
//! `DARKROOM_PYTHON` (an interpreter that can already `import darkroom_app`) bypasses all of this; it is how the
//! app is developed against an existing environment.

use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};

use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Emitter, Manager};
use tokio::sync::{OnceCell, watch};

use crate::error::CmdError;
use crate::paths::{self, Layout, PYTHON_VERSION, TORCH_VERSION};
use crate::proc::{self, RunOutcome};

/// Event name the bootstrap page listens to.
pub const PROGRESS_EVENT: &str = "setup-progress";

/// What `runtime/darkroom-runtime.json` records about a finished install.
#[derive(Debug, Serialize, Deserialize, PartialEq)]
pub struct Marker {
    pub darkroom_version: String,
    pub torch_version: String,
    pub torch_variant: TorchVariant,
}

/// Which torch build fits this machine.
#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum TorchVariant {
    /// NVIDIA GPU found: CUDA 13.0 build.
    Cuda,
    /// No NVIDIA GPU (or no nvidia-smi): CPU build. Preview and export still work, just slowly.
    Cpu,
    /// macOS: PyPI's default build (Metal/CPU); not a release target yet, kept so `cargo run` works there.
    Default,
}

impl TorchVariant {
    /// PyTorch's own package index for this build (used as the only index, so PyPI's torch is never picked);
    /// None for the default build from PyPI.
    fn index_url(self) -> Option<&'static str> {
        match self {
            TorchVariant::Cuda => Some("https://download.pytorch.org/whl/cu130"),
            TorchVariant::Cpu => Some("https://download.pytorch.org/whl/cpu"),
            TorchVariant::Default => None,
        }
    }

    /// Rough (download MB, disk MB) for a full install: Python ~30 MB, darkroom's other dependencies ~100 MB,
    /// plus torch (CUDA build with its NVIDIA libraries ~2.7 GB download, ~6 GB unpacked; CPU build ~250 MB).
    /// Shown to the user before they agree; deliberately rounded up.
    fn estimate_mb(self) -> (u32, u32) {
        match self {
            TorchVariant::Cuda => (3000, 6500),
            TorchVariant::Cpu | TorchVariant::Default => (450, 1500),
        }
    }
}

/// Detects NVIDIA once per app run: `nvidia-smi -L` must succeed and list at least one GPU.
pub async fn torch_variant() -> TorchVariant {
    static VARIANT: OnceCell<TorchVariant> = OnceCell::const_new();
    *VARIANT
        .get_or_init(|| async {
            if cfg!(target_os = "macos") {
                return TorchVariant::Default;
            }
            match proc::command("nvidia-smi").arg("-L").output().await {
                Ok(out)
                    if out.status.success()
                        && String::from_utf8_lossy(&out.stdout).contains("GPU") =>
                {
                    TorchVariant::Cuda
                }
                _ => TorchVariant::Cpu,
            }
        })
        .await
}

/// The answer to "can darkroom start right away?", shown by the bootstrap page.
#[derive(Debug, Serialize)]
pub struct RuntimeStatus {
    /// `ready` (start the backend), `missing` (needs the full download), `outdated` (needs a small update).
    pub state: &'static str,
    /// True when `DARKROOM_PYTHON` points at an interpreter we do not manage.
    pub external: bool,
    /// Where the environment is (or will be) installed; shown to the user.
    pub install_dir: String,
    pub app_version: String,
    pub installed_version: Option<String>,
    pub torch: TorchVariant,
    pub download_mb: u32,
    pub disk_mb: u32,
}

/// The interpreter to run darkroom with, and the folder to run it in.
pub struct PythonCmd {
    pub program: PathBuf,
    /// Set for a development interpreter that sees darkroom only from a source checkout.
    pub cwd: Option<PathBuf>,
}

/// `DARKROOM_PYTHON` override, if set. In debug builds it runs from the repo root (two folders above this crate), so
/// a development interpreter without an installed wheel still imports `darkroom_app` from the checkout.
pub fn external_python() -> Option<PythonCmd> {
    let program = std::env::var_os("DARKROOM_PYTHON").filter(|v| !v.is_empty())?;
    let cwd = if cfg!(debug_assertions) {
        let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("..").join("..");
        root.join("pyproject.toml").is_file().then_some(root)
    } else {
        None
    };
    Some(PythonCmd {
        program: PathBuf::from(program),
        cwd,
    })
}

/// The managed-environment layout under this app's local data folder (`io` error when the OS reports none).
pub fn layout(app: &AppHandle) -> Result<Layout, CmdError> {
    let root = app
        .path()
        .app_local_data_dir()
        .map_err(|e| CmdError::new("io", format!("app data folder unavailable: {e}")))?;
    Ok(Layout::new(root))
}

/// The install marker, or None when it is missing or unreadable (both mean "not ready").
pub fn read_marker(layout: &Layout) -> Option<Marker> {
    let text = std::fs::read_to_string(layout.marker()).ok()?;
    serde_json::from_str(&text).ok()
}

/// `ready` when an override is set or the marker matches this app version and the torch pin; `outdated` when a
/// marker exists but differs (a small update when only darkroom changed); `missing` otherwise. Runs `nvidia-smi`
/// once (cached) to size the download; writes nothing.
pub async fn status(app: &AppHandle) -> Result<RuntimeStatus, CmdError> {
    let layout = layout(app)?;
    let app_version = app.package_info().version.to_string();
    let torch = torch_variant().await;
    let (full_dl, full_disk) = torch.estimate_mb();
    let mut st = RuntimeStatus {
        state: "missing",
        external: false,
        install_dir: layout.runtime_dir().display().to_string(),
        app_version: app_version.clone(),
        installed_version: None,
        torch,
        download_mb: full_dl,
        disk_mb: full_disk,
    };
    if let Some(ext) = external_python() {
        st.state = "ready";
        st.external = true;
        st.install_dir = ext.program.display().to_string();
        return Ok(st);
    }
    let marker = if layout.python().is_file() {
        read_marker(&layout)
    } else {
        None
    };
    if let Some(m) = marker {
        st.installed_version = Some(m.darkroom_version.clone());
        if m.darkroom_version == app_version && m.torch_version == TORCH_VERSION {
            st.state = "ready";
            st.download_mb = 0;
            st.disk_mb = 0;
        } else {
            st.state = "outdated";
            if m.torch_version == TORCH_VERSION && m.torch_variant == torch {
                // only darkroom and maybe a few of its dependencies change
                st.download_mb = 100;
                st.disk_mb = 300;
            }
        }
    }
    Ok(st)
}

/// The interpreter `start_backend` runs: the override, or the managed environment once it is ready.
pub async fn python_for_backend(app: &AppHandle) -> Result<PythonCmd, CmdError> {
    if let Some(ext) = external_python() {
        return Ok(ext);
    }
    let st = status(app).await?;
    if st.state != "ready" {
        return Err(CmdError::new("python_missing", st.install_dir));
    }
    Ok(PythonCmd {
        program: layout(app)?.python(),
        cwd: None,
    })
}

/// Shared state of the (at most one) running install.
pub struct InstallState {
    running: AtomicBool,
    cancel: watch::Sender<bool>,
}

impl Default for InstallState {
    fn default() -> Self {
        Self {
            running: AtomicBool::new(false),
            cancel: watch::Sender::new(false),
        }
    }
}

impl InstallState {
    /// Asks the running install to stop: the current uv child is killed and no further step starts.
    pub fn cancel(&self) {
        self.cancel.send_replace(true);
    }
}

/// Resets `running` however the install ends (success, error, cancel, or the future being dropped).
struct RunningGuard<'a>(&'a AtomicBool);

impl Drop for RunningGuard<'_> {
    fn drop(&mut self) {
        self.0.store(false, Ordering::SeqCst);
    }
}

/// One `setup-progress` event.
#[derive(Clone, Serialize)]
struct Progress {
    /// `python` | `torch` | `darkroom` | `done` | `cancelled` | `error`
    phase: &'static str,
    step: u8,
    total: u8,
    /// One output line from uv, if this event carries one.
    line: Option<String>,
}

const TOTAL_STEPS: u8 = 3;

/// The darkroom wheel to install, first match wins:
/// 1. `DARKROOM_WHEEL` (a .whl file or a source folder with pyproject.toml);
/// 2. the wheel the installer bundled under `<resources>/wheels/` (CI copies it there; tauri.bundle.conf.json);
/// 3. debug builds only: the repo checkout itself (uv builds it with hatchling), so `cargo run` works from source.
fn find_wheel(app: &AppHandle) -> Result<PathBuf, CmdError> {
    if let Some(p) = std::env::var_os("DARKROOM_WHEEL").filter(|v| !v.is_empty()) {
        return Ok(PathBuf::from(p));
    }
    if let Ok(res) = app.path().resource_dir()
        && let Ok(entries) = std::fs::read_dir(res.join("wheels"))
    {
        let mut wheels: Vec<PathBuf> = entries
            .filter_map(|e| e.ok().map(|e| e.path()))
            .filter(|p| p.extension().is_some_and(|x| x == "whl"))
            .collect();
        wheels.sort();
        if let Some(w) = wheels.pop() {
            return Ok(w);
        }
    }
    if cfg!(debug_assertions) {
        let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("..").join("..");
        if root.join("pyproject.toml").is_file() {
            return Ok(std::fs::canonicalize(&root).unwrap_or(root));
        }
    }
    Err(CmdError::new(
        "wheel_missing",
        "no bundled darkroom wheel (resources/wheels/*.whl)",
    ))
}

/// Builds (or updates) the managed environment. The bootstrap page calls this only after the user pressed "agree".
pub async fn install(app: &AppHandle, state: &InstallState) -> Result<(), CmdError> {
    if state.running.swap(true, Ordering::SeqCst) {
        return Err(CmdError::new("busy", "an install is already running"));
    }
    let _guard = RunningGuard(&state.running);
    state.cancel.send_replace(false);

    let result = install_steps(app, state).await;
    let phase = match &result {
        Ok(()) => "done",
        Err(e) if e.code == "cancelled" => "cancelled",
        Err(_) => "error",
    };
    let _ = app.emit(
        PROGRESS_EVENT,
        Progress {
            phase,
            step: TOTAL_STEPS,
            total: TOTAL_STEPS,
            line: None,
        },
    );
    result
}

/// The install steps listed in the module docs, in order; the first failing step's error is returned and nothing
/// after it runs (in particular no marker is written).
async fn install_steps(app: &AppHandle, state: &InstallState) -> Result<(), CmdError> {
    let layout = layout(app)?;
    let uv = paths::find_uv();
    let wheel = find_wheel(app)?;
    let variant = torch_variant().await;
    std::fs::create_dir_all(layout.root()).map_err(|e| CmdError::new("io", e.to_string()))?;

    // Step 1: the interpreter + venv. An existing venv (from a cancelled or older install) is reused.
    if !layout.python().is_file() {
        let runtime = layout.runtime_dir();
        if runtime.exists() {
            // a half-created venv without an interpreter: start clean so `uv venv` does not refuse or prompt
            std::fs::remove_dir_all(&runtime).map_err(|e| CmdError::new("io", e.to_string()))?;
        }
        let mut cmd = uv_command(&uv, &layout);
        cmd.arg("venv")
            .arg("--python")
            .arg(PYTHON_VERSION)
            .arg(&runtime);
        run_step(app, state, "python", 1, cmd).await?;
    } else {
        emit_line(
            app,
            "python",
            1,
            format!("reusing {}", layout.python().display()),
        );
    }

    // Step 2: torch from PyTorch's index. `--index-url` (not extra-index) so PyPI's torch can never be picked.
    let python = layout.python();
    let mut cmd = uv_command(&uv, &layout);
    cmd.args(["pip", "install", "--python"])
        .arg(&python)
        .arg(format!("torch=={TORCH_VERSION}"));
    if let Some(url) = variant.index_url() {
        cmd.arg("--index-url").arg(url);
    }
    run_step(app, state, "torch", 2, cmd).await?;

    // Step 3: darkroom itself (+ HEIC and semantic-index extras, as requirements.txt installs them).
    let requirement = format!("darkroom[heic,semantic] @ {}", paths::file_url(&wheel));
    let mut cmd = uv_command(&uv, &layout);
    cmd.args(["pip", "install", "--python"])
        .arg(&python)
        .args(["--reinstall-package", "darkroom"])
        .arg(requirement);
    run_step(app, state, "darkroom", 3, cmd).await?;

    // Step 4: the marker, written last so only a complete install ever counts as ready.
    let marker = Marker {
        darkroom_version: app.package_info().version.to_string(),
        torch_version: TORCH_VERSION.to_string(),
        torch_variant: variant,
    };
    let text =
        serde_json::to_string_pretty(&marker).map_err(|e| CmdError::new("io", e.to_string()))?;
    std::fs::write(layout.marker(), text).map_err(|e| CmdError::new("io", e.to_string()))?;
    Ok(())
}

/// `uv` with its interpreter and cache kept inside the app folder, user/project uv config ignored (a stray
/// uv.toml must not redirect indexes), only uv-managed Pythons (a system Python could disappear under the venv),
/// and plain line output instead of progress bars.
fn uv_command(uv: &Path, layout: &Layout) -> tokio::process::Command {
    let mut cmd = proc::command(uv);
    cmd.env("UV_PYTHON_INSTALL_DIR", layout.uv_python_dir())
        .env("UV_CACHE_DIR", layout.uv_cache_dir())
        .env("UV_PYTHON_PREFERENCE", "only-managed")
        .env("UV_NO_CONFIG", "1")
        .env("UV_NO_PROGRESS", "1")
        .env_remove("VIRTUAL_ENV")
        .env_remove("UV_PYTHON");
    cmd
}

/// Sends one uv output line to the bootstrap page as a `setup-progress` event (best effort: no window, no error).
fn emit_line(app: &AppHandle, phase: &'static str, step: u8, line: String) {
    let _ = app.emit(
        PROGRESS_EVENT,
        Progress {
            phase,
            step,
            total: TOTAL_STEPS,
            line: Some(line),
        },
    );
}

/// Runs one install step: announces it, streams its output to the page, and maps the outcome to an error code
/// (`cancelled`, `step_failed` with exit code and last lines, `uv_missing` when uv cannot be started, `io`).
async fn run_step(
    app: &AppHandle,
    state: &InstallState,
    phase: &'static str,
    step: u8,
    cmd: tokio::process::Command,
) -> Result<(), CmdError> {
    let _ = app.emit(
        PROGRESS_EVENT,
        Progress {
            phase,
            step,
            total: TOTAL_STEPS,
            line: None,
        },
    );
    let sink: Arc<dyn Fn(String) + Send + Sync> = {
        let app = app.clone();
        Arc::new(move |line| emit_line(&app, phase, step, line))
    };
    match proc::run_streaming(cmd, state.cancel.subscribe(), sink).await {
        Ok(RunOutcome::Cancelled) => Err(CmdError::new("cancelled", phase)),
        Ok(RunOutcome::Exited { success: true, .. }) => Ok(()),
        Ok(RunOutcome::Exited { code, tail, .. }) => Err(CmdError::new(
            "step_failed",
            format!(
                "{phase}: exit {}\n{tail}",
                code.map_or("?".to_string(), |c| c.to_string())
            ),
        )),
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => Err(CmdError::new(
            "uv_missing",
            format!("{}: {e}", paths::find_uv().display()),
        )),
        Err(e) => Err(CmdError::new("io", e.to_string())),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn marker_round_trips_with_lowercase_variant() {
        let m = Marker {
            darkroom_version: "0.1.0".into(),
            torch_version: TORCH_VERSION.into(),
            torch_variant: TorchVariant::Cuda,
        };
        let text = serde_json::to_string(&m).unwrap();
        assert!(text.contains("\"cuda\""));
        assert_eq!(serde_json::from_str::<Marker>(&text).unwrap(), m);
    }

    #[test]
    fn cpu_and_cuda_use_pytorch_indexes() {
        assert!(TorchVariant::Cuda.index_url().unwrap().ends_with("/cu130"));
        assert!(TorchVariant::Cpu.index_url().unwrap().ends_with("/cpu"));
        assert!(TorchVariant::Default.index_url().is_none());
    }
}
