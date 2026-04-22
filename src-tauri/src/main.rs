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
    // First, fast-path: honor `M3_BIN` if set (explicit override).
    if let Ok(v) = std::env::var("M3_BIN") {
        let p = std::path::PathBuf::from(v);
        if p.exists() {
            return Some(p);
        }
    }

    // 1. $PATH and common system locations.
    let direct = [
        "m3",                           // $PATH (pipx, venv activate, etc.)
        "/opt/homebrew/bin/m3",         // Homebrew on Apple Silicon
        "/usr/local/bin/m3",            // Homebrew on Intel, pip --user
    ];
    for name in direct {
        if let Ok(p) = which::which(name) {
            return Some(p);
        }
    }

    // 2. User-local and toolchain-managed Python installs. Finder-launched
    //    apps don't inherit the login shell PATH, so these paths are often
    //    invisible to `which`. We check them explicitly.
    let home = match dirs_like_home() {
        Some(h) => h,
        None => return None,
    };

    let fixed = [
        home.join(".local/bin/m3"),              // pipx default, pip --user
        home.join(".local/share/pipx/venvs/m3/bin/m3"),
        home.join(".pyenv/shims/m3"),
        home.join(".asdf/shims/m3"),
        home.join("miniconda3/bin/m3"),
        home.join("anaconda3/bin/m3"),
    ];
    for p in &fixed {
        if p.exists() {
            return Some(p.clone());
        }
    }

    // 3. Glob the mise installs dir — version dirs vary.
    //    ~/.local/share/mise/installs/python/*/bin/m3
    let mise_root = home.join(".local/share/mise/installs/python");
    if let Ok(entries) = std::fs::read_dir(&mise_root) {
        for entry in entries.flatten() {
            let candidate = entry.path().join("bin/m3");
            if candidate.exists() {
                return Some(candidate);
            }
        }
    }

    None
}

fn dirs_like_home() -> Option<std::path::PathBuf> {
    // Tauri drags in `dirs` transitively; std::env::var("HOME") is sufficient
    // and avoids an explicit dep.
    std::env::var_os("HOME").map(std::path::PathBuf::from)
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
