// M3 desktop shell.
//
// Responsibilities at launch:
//   1. Reconcile a private Python venv at <app_data>/runtime/venv with the
//      m3 wheel bundled inside the .app. On a fresh install or after an
//      auto-update lands a new wheel, this runs `pip install` once; otherwise
//      it's a no-op.
//   2. Spawn `m3 start --port 7007` from that venv as a child process.
//   3. Wait for the local HTTP server, then navigate the webview from the
//      static splash to http://127.0.0.1:7007.
//
// Why a managed venv instead of pipx: end users get a single .app and never
// see a pip/pipx command. The Tauri auto-updater ships a new bundle (with a
// new wheel inside), and the next launch silently reconciles. The user only
// sees a "Restart now" banner.
//
// Still required on the user's system: a `python3` (3.12+) on PATH or in one
// of the common Python install locations. Bundling python-build-standalone
// into the .app to drop that requirement is the planned next step; it would
// roughly +30 MB to the bundle and let us swap to a fully sealed runtime.

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::net::TcpStream;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::thread::sleep;
use std::time::{Duration, Instant};

use tauri::{AppHandle, Manager, RunEvent, WindowEvent};

const DEFAULT_PORT: u16 = 7007;
const STARTUP_TIMEOUT_SECS: u64 = 25;

/// Handle to the child m3 server, kept alive for the lifetime of the app.
struct M3Child(Mutex<Option<Child>>);

// ── Python discovery ────────────────────────────────────────────────────────

fn dirs_like_home() -> Option<PathBuf> {
    std::env::var_os("HOME").map(PathBuf::from)
}

/// The m3 wheel's `requires-python` is `>=3.12`. Stock macOS still ships 3.9
/// at /usr/bin/python3, so we can't just take the first python on PATH —
/// every candidate has to pass this probe.
const MIN_PY_MAJOR: u32 = 3;
const MIN_PY_MINOR: u32 = 12;

fn python_version_ok(python: &Path) -> bool {
    let script = format!(
        "import sys; sys.exit(0 if sys.version_info >= ({MIN_PY_MAJOR}, {MIN_PY_MINOR}) else 1)"
    );
    Command::new(python)
        .args(["-c", &script])
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status()
        .map(|s| s.success())
        .unwrap_or(false)
}

fn find_system_python() -> Option<PathBuf> {
    if let Ok(v) = std::env::var("M3_PYTHON") {
        let p = PathBuf::from(v);
        if p.exists() && python_version_ok(&p) {
            return Some(p);
        }
    }

    let mut candidates: Vec<PathBuf> = Vec::new();

    // PATH lookups — try newer versions first so we don't accidentally pick
    // /usr/bin/python3 (3.9 on macOS) over a Homebrew/mise 3.12+.
    for cand in ["python3.13", "python3.12", "python3", "python"] {
        if let Ok(p) = which::which(cand) {
            candidates.push(p);
        }
    }

    // Fixed system locations — same priority order.
    candidates.extend([
        PathBuf::from("/opt/homebrew/bin/python3.13"),
        PathBuf::from("/opt/homebrew/bin/python3.12"),
        PathBuf::from("/opt/homebrew/bin/python3"),
        PathBuf::from("/usr/local/bin/python3.13"),
        PathBuf::from("/usr/local/bin/python3.12"),
        PathBuf::from("/usr/local/bin/python3"),
        // /usr/bin/python3 is intentionally last — it's macOS's stock 3.9 and
        // will fail the version probe anyway, but listing it keeps the search
        // honest.
        PathBuf::from("/usr/bin/python3"),
    ]);

    if let Some(home) = dirs_like_home() {
        candidates.extend([
            home.join(".pyenv/shims/python3"),
            home.join(".asdf/shims/python3"),
            home.join(".local/bin/python3"),
        ]);

        // Mise installs live under per-version dirs, e.g.
        // ~/.local/share/mise/installs/python/3.12.12/bin/python3. Finder-
        // launched apps don't get the mise shim in PATH so we have to scan.
        // Sorted descending so the newest version wins.
        let mise_root = home.join(".local/share/mise/installs/python");
        if let Ok(entries) = std::fs::read_dir(&mise_root) {
            let mut found: Vec<PathBuf> = entries
                .flatten()
                .map(|e| e.path().join("bin/python3"))
                .filter(|p| p.exists())
                .collect();
            found.sort();
            found.reverse();
            candidates.extend(found);
        }
    }

    candidates
        .into_iter()
        .find(|p| p.exists() && python_version_ok(p))
}

// ── Bundled wheel discovery ─────────────────────────────────────────────────

fn find_bundled_wheel(root: &Path) -> Option<PathBuf> {
    fn walk(dir: &Path) -> Option<PathBuf> {
        let entries = std::fs::read_dir(dir).ok()?;
        for entry in entries.flatten() {
            let p = entry.path();
            if p.is_dir() {
                if let Some(found) = walk(&p) {
                    return Some(found);
                }
            } else if let Some(name) = p.file_name().and_then(|s| s.to_str()) {
                if name.starts_with("m3-") && name.ends_with(".whl") {
                    return Some(p);
                }
            }
        }
        None
    }
    walk(root)
}

/// Cheap fingerprint to decide "did this wheel change since we last installed".
/// Size + mtime is robust enough — we don't need a content hash.
fn wheel_fingerprint(path: &Path) -> std::io::Result<String> {
    let meta = std::fs::metadata(path)?;
    let size = meta.len();
    let mtime = meta
        .modified()?
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0);
    Ok(format!("{size}-{mtime}"))
}

// ── Venv management ─────────────────────────────────────────────────────────

fn venv_bin(venv: &Path, name: &str) -> PathBuf {
    if cfg!(windows) {
        venv.join("Scripts").join(format!("{name}.exe"))
    } else {
        venv.join("bin").join(name)
    }
}

fn run_capturing(cmd: &mut Command) -> Result<(), String> {
    let out = cmd.output().map_err(|e| format!("spawn failed: {e}"))?;
    if out.status.success() {
        return Ok(());
    }
    let stderr = String::from_utf8_lossy(&out.stderr);
    let stdout = String::from_utf8_lossy(&out.stdout);
    Err(format!(
        "exit {}\nstdout: {}\nstderr: {}",
        out.status,
        stdout.trim(),
        stderr.trim()
    ))
}

fn create_venv(python: &Path, venv: &Path) -> Result<(), String> {
    run_capturing(
        Command::new(python)
            .args(["-m", "venv", venv.to_str().unwrap()]),
    )
    .map_err(|e| format!("python -m venv failed: {e}"))
}

fn install_wheel(venv: &Path, wheel: &Path) -> Result<(), String> {
    let pip = venv_bin(venv, "pip");
    // --upgrade so that bumping versions (or unchanged version with rebuilt
    // dependencies) actually replaces the installed copy.
    run_capturing(
        Command::new(&pip)
            .args(["install", "--upgrade", "--quiet", wheel.to_str().unwrap()]),
    )
    .map_err(|e| format!("pip install failed: {e}"))
}

/// Reconcile the user-data venv with the bundled wheel and return the path
/// to the m3 entry point to spawn.
fn ensure_m3_runtime<R: tauri::Runtime>(app: &AppHandle<R>) -> Result<PathBuf, String> {
    // Power-user override: useful for `M3_BIN=$(which m3)` when iterating
    // on the Python side without rebuilding the .app each time.
    if let Ok(v) = std::env::var("M3_BIN") {
        let p = PathBuf::from(v);
        if p.exists() {
            return Ok(p);
        }
    }

    let resource_dir = app
        .path()
        .resource_dir()
        .map_err(|e| format!("resource dir unavailable: {e}"))?;
    let wheel = find_bundled_wheel(&resource_dir).ok_or_else(|| {
        "Bundled m3 wheel not found in app resources. This is a packaging bug — \
         scripts/build-wheel.sh must run before `cargo tauri build`."
            .to_string()
    })?;
    let fingerprint = wheel_fingerprint(&wheel)
        .map_err(|e| format!("could not stat bundled wheel: {e}"))?;

    let data_dir = app
        .path()
        .app_local_data_dir()
        .map_err(|e| format!("app data dir unavailable: {e}"))?;
    let runtime_dir = data_dir.join("runtime");
    let venv_dir = runtime_dir.join("venv");
    let marker = runtime_dir.join("installed_fingerprint");
    let m3_bin = venv_bin(&venv_dir, "m3");

    let already_synced = m3_bin.exists()
        && std::fs::read_to_string(&marker)
            .ok()
            .as_deref()
            .map(str::trim)
            == Some(fingerprint.as_str());
    if already_synced {
        return Ok(m3_bin);
    }

    std::fs::create_dir_all(&runtime_dir).map_err(|e| e.to_string())?;

    // A previous run may have left a venv built against an old Python (e.g.
    // /usr/bin/python3 = 3.9 on macOS, which can't host m3 >= 3.12). Detect
    // that and rebuild — never reuse a broken interpreter.
    let venv_python = venv_bin(&venv_dir, "python3");
    let venv_is_usable = venv_dir.exists() && python_version_ok(&venv_python);
    if venv_dir.exists() && !venv_is_usable {
        std::fs::remove_dir_all(&venv_dir).map_err(|e| e.to_string())?;
    }

    if !venv_is_usable {
        let python = find_system_python().ok_or_else(|| {
            "Python 3.12 or newer was not found on this system. M3 needs Python \
             to run. Install it from python.org or your package manager and \
             relaunch."
                .to_string()
        })?;
        create_venv(&python, &venv_dir)?;
    }

    install_wheel(&venv_dir, &wheel)?;
    std::fs::write(&marker, &fingerprint).map_err(|e| e.to_string())?;
    Ok(m3_bin)
}

// ── Server lifecycle ────────────────────────────────────────────────────────

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

/// Build a richer PATH for the spawned m3 server. Finder-launched apps
/// inherit only the system default PATH (/usr/bin:/bin:/usr/sbin:/sbin),
/// so the m3 server can't find user-installed AI CLIs (claude in
/// ~/.local/bin, gemini under mise, etc) via shutil.which(). We prepend
/// the common bin dirs and every mise installation's bin/ so detection
/// matches what the user sees in their terminal.
fn augmented_path() -> String {
    let mut entries: Vec<PathBuf> = Vec::new();

    if let Some(home) = dirs_like_home() {
        entries.extend([
            home.join(".local/bin"),
            home.join(".cargo/bin"),
            home.join(".pyenv/shims"),
            home.join(".asdf/shims"),
        ]);

        // Every mise tool install has a bin/ — globbing them all keeps node /
        // python / etc. in PATH without parsing mise's config.
        let mise_root = home.join(".local/share/mise/installs");
        if let Ok(tools) = std::fs::read_dir(&mise_root) {
            for tool in tools.flatten() {
                if let Ok(versions) = std::fs::read_dir(tool.path()) {
                    for v in versions.flatten() {
                        let bin = v.path().join("bin");
                        if bin.is_dir() {
                            entries.push(bin);
                        }
                    }
                }
            }
        }
    }

    entries.extend([
        PathBuf::from("/opt/homebrew/bin"),
        PathBuf::from("/opt/homebrew/sbin"),
        PathBuf::from("/usr/local/bin"),
        PathBuf::from("/usr/local/sbin"),
    ]);

    let existing = std::env::var("PATH").unwrap_or_default();

    let mut seen: std::collections::HashSet<PathBuf> = std::collections::HashSet::new();
    let mut out: Vec<String> = Vec::new();
    for p in &entries {
        if p.is_dir() && seen.insert(p.clone()) {
            out.push(p.to_string_lossy().into_owned());
        }
    }
    if !existing.is_empty() {
        out.push(existing);
    }
    out.join(":")
}

fn spawn_m3_server(m3: &Path, port: u16) -> Result<Child, String> {
    if port_is_open(port) {
        // Something already listens — assume it's a dev m3 we want to reuse.
        return Command::new(if cfg!(windows) { "cmd" } else { "true" })
            .args(if cfg!(windows) { &["/C", "exit"][..] } else { &[] })
            .spawn()
            .map_err(|e| e.to_string());
    }
    Command::new(m3)
        .args(["start", "--port", &port.to_string(), "--host", "127.0.0.1"])
        .env("PATH", augmented_path())
        .stdout(Stdio::inherit())
        .stderr(Stdio::inherit())
        .spawn()
        .map_err(|e| format!("failed to spawn m3 start: {e}"))
}

// ── Entrypoint ──────────────────────────────────────────────────────────────

fn fail_dialog<R: tauri::Runtime>(app: &AppHandle<R>, title: &str, body: &str) -> ! {
    use tauri_plugin_dialog::{DialogExt, MessageDialogKind};
    app.dialog()
        .message(body)
        .kind(MessageDialogKind::Error)
        .title(title)
        .blocking_show();
    std::process::exit(1);
}

fn main() {
    let port = DEFAULT_PORT;
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_process::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .manage(M3Child(Mutex::new(None)))
        .setup(move |app| {
            let handle = app.handle().clone();

            let m3_path = match ensure_m3_runtime(&handle) {
                Ok(p) => p,
                Err(e) => fail_dialog(&handle, "M3 runtime setup failed", &e),
            };

            let child = match spawn_m3_server(&m3_path, port) {
                Ok(c) => c,
                Err(e) => fail_dialog(&handle, "M3 failed to start", &e),
            };

            if let Err(e) = wait_for_server(port) {
                fail_dialog(&handle, "M3 server startup timed out", &e);
            }

            let url = format!("http://127.0.0.1:{port}");
            if let Some(window) = handle.get_webview_window("main") {
                let _ = window.navigate(url.parse().unwrap());
            }

            handle.state::<M3Child>().0.lock().unwrap().replace(child);
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
