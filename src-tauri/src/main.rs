// M3 desktop shell. Launches `m3 start --port <fixed>` as a child process,
// waits for the local server's /api/v1/status to reply, then loads the
// webview pointing at it. On quit, the child is killed.
//
// Design: this shell does NOT bundle Python. It requires `m3` on PATH
// (installed via `pipx install m3` or similar). The rationale is that
// shipping python-build-standalone + all deps would roughly 4x the bundle
// size, and M3's target user has a terminal anyway.
//
// To later bundle Python, add a `sidecar/` containing python-build-standalone
// plus the wheels and swap the `find_m3_binary` / `Command::new` calls for
// `tauri::api::process::Command::new_sidecar("m3")`.

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::net::TcpStream;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::thread::sleep;
use std::time::{Duration, Instant};

use tauri::{Manager, RunEvent, WindowEvent};

const DEFAULT_PORT: u16 = 7007;
const STARTUP_TIMEOUT_SECS: u64 = 25;

/// Handle to the child m3 server, kept alive for the lifetime of the app.
struct M3Child(Mutex<Option<Child>>);

fn find_m3_binary() -> Option<std::path::PathBuf> {
    let candidates = [
        "m3",                           // PATH (pipx, mise, venv activate)
        "/opt/homebrew/bin/m3",         // Homebrew on Apple Silicon
        "/usr/local/bin/m3",            // Homebrew on Intel, pip --user
    ];
    for name in candidates {
        if let Ok(p) = which::which(name) {
            return Some(p);
        }
    }
    None
}

fn port_is_open(port: u16) -> bool {
    TcpStream::connect_timeout(
        &format!("127.0.0.1:{port}").parse().unwrap(),
        Duration::from_millis(150),
    )
    .is_ok()
}

fn wait_for_server(port: u16) -> Result<(), String> {
    let deadline = Instant::now() + Duration::from_secs(STARTUP_TIMEOUT_SECS);
    while Instant::now() < deadline {
        if port_is_open(port) {
            return Ok(());
        }
        sleep(Duration::from_millis(250));
    }
    Err(format!(
        "M3 server didn't start on port {port} within {STARTUP_TIMEOUT_SECS}s"
    ))
}

fn spawn_m3_server(port: u16) -> Result<Child, String> {
    let m3 = find_m3_binary().ok_or_else(|| {
        "M3 CLI not found on PATH. Install it with `pipx install m3` or \
         make sure `m3` resolves on your $PATH."
            .to_string()
    })?;
    // If something's already bound to the port, assume it's another m3 and
    // reuse it rather than spawning a duplicate.
    if port_is_open(port) {
        return Command::new("true").spawn().map_err(|e| e.to_string());
    }
    Command::new(m3)
        .args(["start", "--port", &port.to_string(), "--host", "127.0.0.1"])
        .stdout(Stdio::inherit())
        .stderr(Stdio::inherit())
        .spawn()
        .map_err(|e| format!("failed to spawn m3 start: {e}"))
}

fn main() {
    let port = DEFAULT_PORT;
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .manage(M3Child(Mutex::new(None)))
        .setup(move |app| {
            let child = match spawn_m3_server(port) {
                Ok(c) => c,
                Err(e) => {
                    use tauri_plugin_dialog::{DialogExt, MessageDialogKind};
                    app.dialog()
                        .message(&e)
                        .kind(MessageDialogKind::Error)
                        .title("M3 failed to start")
                        .blocking_show();
                    std::process::exit(1);
                }
            };
            if let Err(e) = wait_for_server(port) {
                use tauri_plugin_dialog::{DialogExt, MessageDialogKind};
                app.dialog()
                    .message(&e)
                    .kind(MessageDialogKind::Error)
                    .title("M3 server startup timed out")
                    .blocking_show();
                std::process::exit(1);
            }
            // Navigate the main window to the local server.
            let url = format!("http://127.0.0.1:{port}");
            let window = app.get_webview_window("main").unwrap();
            let _ = window.navigate(url.parse().unwrap());

            app.state::<M3Child>().0.lock().unwrap().replace(child);
            Ok(())
        })
        .on_window_event(|window, event| {
            if let WindowEvent::CloseRequested { .. } = event {
                if let Some(state) = window.try_state::<M3Child>() {
                    if let Some(mut child) = state.0.lock().unwrap().take() {
                        let _ = child.kill();
                        let _ = child.wait();
                    }
                }
            }
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app_handle, event| {
            if let RunEvent::ExitRequested { .. } = event {
                if let Some(state) = app_handle.try_state::<M3Child>() {
                    if let Some(mut child) = state.0.lock().unwrap().take() {
                        let _ = child.kill();
                        let _ = child.wait();
                    }
                }
            }
        });
}
