//! darkroom desktop shell (Tauri 2), plan-v2 §4.
//!
//! The window first shows the bundled bootstrap page (`desktop/bootstrap/`). That page asks `runtime_status`; when
//! the managed Python environment is missing it explains the download and only after the user agrees calls
//! `install_runtime` (progress arrives as `setup-progress` events, `cancel_install` stops it). Once the
//! environment is ready it asks `preset_setup_status` - with no usable preset folder configured the user picks one
//! (`set_preset_dir`, the dialog plugin's folder picker) - and then calls `start_backend`, which runs
//! `python -s -m darkroom_app` on a free 127.0.0.1 port and navigates this window to the editor. Exiting the app - or the app crashing or being killed - ends the backend
//! and any running install (`killjob`).
//!
//! Module map: `runtime` (is the managed Python environment ready, and installing it with uv), `backend` (the Python
//! server child process), `proc` (how every child process is started and its output read), `paths` (where things live
//! on disk), `setup` (the preset folder before the first start), `killjob` (children die with this process), `error`
//! (the one error shape the page receives). This crate holds no photo-editing logic: everything the
//! user edits goes through the Python backend's HTTP API, exactly as in a browser.
//!
//! Security boundary: only the bundled bootstrap page may call these six commands and open the folder picker
//! (`build.rs` + `capabilities/default.json`); once the window shows the editor served from 127.0.0.1, no command is reachable.

// Release builds are GUI apps on Windows (no console window); debug builds keep the console for logs.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod backend;
mod error;
mod killjob;
mod paths;
mod proc;
mod runtime;
mod setup;

use tauri::{AppHandle, Manager, RunEvent, State};

use error::CmdError;
use runtime::{InstallState, RuntimeStatus};
use setup::PresetSetup;

/// Reports whether the managed environment is ready, missing or outdated, with the download size to show the user.
/// Reads only; never downloads anything.
#[tauri::command]
async fn runtime_status(app: AppHandle) -> Result<RuntimeStatus, CmdError> {
    runtime::status(&app).await
}

/// Downloads and installs the environment. The page calls this only after the user pressed "agree".
#[tauri::command]
async fn install_runtime(app: AppHandle, state: State<'_, InstallState>) -> Result<(), CmdError> {
    runtime::install(&app, &state).await
}

/// Stops a running install (the current uv child is killed); a no-op when nothing is installing.
#[tauri::command]
fn cancel_install(state: State<'_, InstallState>) {
    state.cancel();
}

/// Is a usable preset folder configured? The page asks before `start_backend`: the backend cannot start without
/// one, and an installed copy has no other place to set it (`setup`). Reads only.
#[tauri::command]
async fn preset_setup_status(app: AppHandle) -> Result<PresetSetup, CmdError> {
    setup::status(&app).await
}

/// Writes the folder the user picked as `preset_dir`, through the backend's own `settings set` (its checks apply).
#[tauri::command]
async fn set_preset_dir(app: AppHandle, path: String) -> Result<PresetSetup, CmdError> {
    setup::set_preset_dir(&app, &path).await
}

/// Starts the backend and navigates the window to it; returns the editor URL.
#[tauri::command]
async fn start_backend(app: AppHandle) -> Result<String, CmdError> {
    backend::start(&app).await
}

fn main() {
    let app = tauri::Builder::default()
        // the native folder picker for "where are your presets" (only the bootstrap page may open it)
        .plugin(tauri_plugin_dialog::init())
        .manage(InstallState::default())
        .manage(backend::BackendState::default())
        .invoke_handler(tauri::generate_handler![
            runtime_status,
            install_runtime,
            cancel_install,
            preset_setup_status,
            set_preset_dir,
            start_backend
        ])
        .build(tauri::generate_context!())
        .expect("error while building the darkroom desktop app");

    app.run(|handle, event| {
        if let RunEvent::Exit = event {
            // No child outlives the app: the backend server and an unfinished uv install are both stopped.
            // These are the polite path; tao exits the process right after this callback, before any async kill
            // could run, so the hard guarantee is the kill-on-close job every child is in (`killjob`), which also
            // covers a crash or a forced kill of this process.
            backend::stop(handle);
            handle.state::<InstallState>().cancel();
        }
    });
}
