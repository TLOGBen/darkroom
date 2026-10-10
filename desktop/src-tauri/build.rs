//! Generates the Tauri context and the permission set of this app's own commands.
//!
//! Every command the bootstrap page may call is listed here; tauri-build then generates one
//! `allow-<command>` permission per entry, and `capabilities/default.json` grants exactly those to the
//! main window (and nothing to any remote page, such as the editor served from 127.0.0.1).
fn main() {
    tauri_build::try_build(tauri_build::Attributes::new().app_manifest(
        tauri_build::AppManifest::new().commands(&[
            "runtime_status",
            "install_runtime",
            "cancel_install",
            "preset_setup_status",
            "set_preset_dir",
            "start_backend",
        ]),
    ))
    .expect("failed to run tauri-build");
}
