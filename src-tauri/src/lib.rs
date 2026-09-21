use std::env;
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, SystemTime};

use serde_json::Value;
use tauri::menu::{CheckMenuItem, Menu, MenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{AppHandle, Emitter, Manager, PhysicalPosition, WebviewWindow};
use tauri_plugin_autostart::{MacosLauncher, ManagerExt};
use tauri_plugin_global_shortcut::{Code, GlobalShortcutExt, Modifiers, Shortcut, ShortcutState};

/// How often the companion re-reads the sessions the agent hooks write.
const POLL_INTERVAL: Duration = Duration::from_millis(250);

/// How often the pointer is tested against the character. A window that is
/// ignoring cursor events cannot report that the pointer arrived, so the
/// position has to be polled rather than listened for.
const HIT_TEST_INTERVAL: Duration = Duration::from_millis(60);

/// How often a dragged position is committed to disk. Dragging emits a move
/// event per frame, so the writes are batched instead of hitting the disk.
const POSITION_FLUSH_INTERVAL: Duration = Duration::from_millis(1000);

/// The only protocol version this build understands. An event written by a
/// future version is ignored rather than misread.
const PROTOCOL_VERSION: i64 = 1;

/// A session that has stopped writing is ignored, so an agent that crashed
/// mid-turn cannot leave the companion stuck on `working` forever.
const DEFAULT_SESSION_TTL_SECONDS: u64 = 600;

/// Which state wins when several sessions are live, most urgent first. Needs
/// beats busy: a session waiting on the user must not be hidden by another
/// session that is merely running.
const STATE_PRIORITY: [&str; 6] = ["waiting", "error", "working", "success", "thinking", "idle"];

/// Character geometry in CSS pixels, mirroring `.pixel-pet` in styles.css.
/// Everything outside this box is transparent, so a click there belongs to
/// whatever is behind the companion.
const PET_SIZE: f64 = 192.0;
const PET_RIGHT: f64 = 20.0;
const PET_BOTTOM: f64 = 18.0;

/// Set while a menu is open. Menus can extend past the character, and in a
/// click-through window the item under the pointer would be unreachable.
static FORCED_INTERACTIVE: AtomicBool = AtomicBool::new(false);

fn state_dir_override() -> Option<PathBuf> {
    std::env::var_os("PIXELPRESENCE_DIR").map(PathBuf::from)
}

fn home_dir() -> PathBuf {
    std::env::var_os("USERPROFILE")
        .or_else(|| std::env::var_os("HOME"))
        .map(PathBuf::from)
        .expect("no home directory to resolve the companion state directory")
}

/// Directory both sides use for companion state. One file per session lives
/// inside it, so several agents can drive one companion.
fn state_dir() -> PathBuf {
    state_dir_override().unwrap_or_else(|| home_dir().join(".pixelpresence"))
}

fn sessions_dir() -> PathBuf {
    state_dir().join("sessions")
}

/// Where the dragged window position is remembered. Separate from the session
/// files, which the agent hook rewrites on every event.
fn window_state_file() -> PathBuf {
    state_dir().join("window.json")
}

fn session_ttl_seconds() -> u64 {
    std::env::var("PIXELPRESENCE_SESSION_TTL_SECONDS")
        .ok()
        .and_then(|raw| raw.parse().ok())
        .unwrap_or(DEFAULT_SESSION_TTL_SECONDS)
}

fn state_rank(state: &str) -> Option<usize> {
    STATE_PRIORITY
        .iter()
        .position(|candidate| *candidate == state)
}

/// One session's last reported state, with the rank that decides whether it
/// outranks another session's.
#[derive(Debug, Clone, PartialEq)]
struct Candidate {
    value: Value,
    rank: usize,
}

/// Parse and validate a session file. Returns `None` for anything this build
/// should not act on: an unknown protocol version, a malformed body, or a
/// state outside the protocol.
fn parse_candidate(text: &str) -> Option<Candidate> {
    let value: Value = serde_json::from_str(text).ok()?;

    if value.get("version").and_then(Value::as_i64) != Some(PROTOCOL_VERSION) {
        return None;
    }

    let state = value.get("state").and_then(Value::as_str)?;
    let rank = state_rank(state)?;

    Some(Candidate { value, rank })
}

fn reported_at(candidate: &Candidate) -> &str {
    candidate
        .value
        .get("timestamp")
        .and_then(Value::as_str)
        .unwrap_or("")
}

/// The session the companion should be reflecting.
///
/// Urgency first, then the most recent report within the same urgency, so the
/// choice is stable and explainable rather than dependent on read order.
fn pick(candidates: Vec<Candidate>) -> Option<Candidate> {
    candidates.into_iter().min_by(|a, b| {
        a.rank
            .cmp(&b.rank)
            .then_with(|| reported_at(b).cmp(reported_at(a)))
    })
}

fn load_candidates(directory: &Path, ttl_seconds: u64) -> Vec<Candidate> {
    let Ok(entries) = fs::read_dir(directory) else {
        return Vec::new();
    };

    let now = SystemTime::now();
    let mut candidates = Vec::new();

    for entry in entries.flatten() {
        let path = entry.path();
        if path.extension().and_then(|extension| extension.to_str()) != Some("json") {
            continue;
        }

        let age = entry
            .metadata()
            .ok()
            .and_then(|metadata| metadata.modified().ok())
            .and_then(|modified| now.duration_since(modified).ok())
            .map(|age| age.as_secs())
            .unwrap_or(u64::MAX);
        if age > ttl_seconds {
            continue;
        }

        if let Ok(text) = fs::read_to_string(&path) {
            if let Some(candidate) = parse_candidate(&text) {
                candidates.push(candidate);
            }
        }
    }

    candidates
}

/// What to show when nothing is live. Deliberately timestamp-free so the
/// payload is byte-stable and only reaches the frontend once.
fn resting_event() -> Value {
    serde_json::json!({
        "version": PROTOCOL_VERSION,
        "type": "agent.state",
        "agent": "pixelpresence",
        "state": "idle",
        "label": null,
        "session_id": null,
        "profile": null,
    })
}

fn load_remembered_position() -> Option<PhysicalPosition<i32>> {
    let text = fs::read_to_string(window_state_file()).ok()?;
    let value: Value = serde_json::from_str(&text).ok()?;
    Some(PhysicalPosition::new(
        value.get("x")?.as_i64()? as i32,
        value.get("y")?.as_i64()? as i32,
    ))
}

fn remember_position(position: PhysicalPosition<i32>) {
    let target = window_state_file();
    let Some(parent) = target.parent() else {
        return;
    };
    if fs::create_dir_all(parent).is_err() {
        return;
    }

    let scratch = target.with_extension("tmp");
    let body = serde_json::json!({ "x": position.x, "y": position.y }).to_string();
    if fs::write(&scratch, body).is_ok() {
        let _ = fs::rename(&scratch, &target);
    }
}

/// A remembered position is only reused while it still lands on a monitor:
/// unplugging a display would otherwise leave the window somewhere the user
/// cannot reach or drag back.
fn is_reachable(window: &WebviewWindow, position: PhysicalPosition<i32>) -> bool {
    let Ok(monitors) = window.available_monitors() else {
        return false;
    };

    monitors.iter().any(|monitor| {
        let area = monitor.work_area();
        let left = area.position.x;
        let top = area.position.y;
        let right = left + area.size.width as i32;
        let bottom = top + area.size.height as i32;
        position.x >= left - 8
            && position.x + 48 <= right
            && position.y >= top - 8
            && position.y + 48 <= bottom
    })
}

fn position_bottom_right(window: &WebviewWindow) -> tauri::Result<()> {
    let Some(monitor) = window.primary_monitor()? else {
        return Ok(());
    };

    let work_area = monitor.work_area();
    let size = window.outer_size()?;
    let margin = 24;
    let x = work_area.position.x + work_area.size.width as i32 - size.width as i32 - margin;
    let y = work_area.position.y + work_area.size.height as i32 - size.height as i32 - margin;

    window.set_position(PhysicalPosition::new(x, y))
}

/// Restore where the user last left the companion, falling back to the corner.
fn place_window(window: &WebviewWindow) -> tauri::Result<()> {
    if let Some(position) = load_remembered_position() {
        if is_reachable(window, position) {
            return window.set_position(position);
        }
    }

    position_bottom_right(window)
}

fn remember_moves(window: WebviewWindow) {
    let pending: Arc<Mutex<Option<(i32, i32)>>> = Arc::new(Mutex::new(None));

    let slot = Arc::clone(&pending);
    window.on_window_event(move |event| {
        if let tauri::WindowEvent::Moved(position) = event {
            if let Ok(mut pending) = slot.lock() {
                *pending = Some((position.x, position.y));
            }
        }
    });

    thread::spawn(move || loop {
        thread::sleep(POSITION_FLUSH_INTERVAL);
        let next = pending.lock().ok().and_then(|mut slot| slot.take());
        if let Some((x, y)) = next {
            remember_position(PhysicalPosition::new(x, y));
        }
    });
}

fn pointer_over_character(window: &WebviewWindow) -> bool {
    let (Ok(cursor), Ok(origin), Ok(size), Ok(scale)) = (
        window.cursor_position(),
        window.outer_position(),
        window.outer_size(),
        window.scale_factor(),
    ) else {
        // If the query fails, stay interactive: an unreachable window is worse
        // than one that occasionally swallows a click.
        return true;
    };

    let width = size.width as f64 / scale;
    let height = size.height as f64 / scale;
    let left = origin.x as f64 + (width - PET_RIGHT - PET_SIZE) * scale;
    let top = origin.y as f64 + (height - PET_BOTTOM - PET_SIZE) * scale;

    cursor.x >= left
        && cursor.x < left + PET_SIZE * scale
        && cursor.y >= top
        && cursor.y < top + PET_SIZE * scale
}

/// Keep the transparent majority of the window click-through, handing input
/// back only while the pointer is actually over the character.
fn watch_pointer(window: WebviewWindow) {
    thread::spawn(move || {
        let _ = window.set_ignore_cursor_events(true);
        let mut interactive = false;

        loop {
            thread::sleep(HIT_TEST_INTERVAL);

            if !window.is_visible().unwrap_or(false) {
                continue;
            }

            let wanted =
                FORCED_INTERACTIVE.load(Ordering::Relaxed) || pointer_over_character(&window);
            if wanted == interactive {
                continue;
            }

            if window.set_ignore_cursor_events(!wanted).is_ok() {
                interactive = wanted;
            }
        }
    });
}

fn toggle_companion(app: &AppHandle) {
    let Some(window) = app.get_webview_window("main") else {
        return;
    };

    if window.is_visible().unwrap_or(false) {
        let _ = window.hide();
    } else {
        let _ = window.show();
        let _ = window.set_focus();
    }
}

fn running_from_cargo_profile(executable: &Path, cargo_profile: &Path) -> bool {
    executable.parent() == Some(cargo_profile)
}

fn installed_build() -> bool {
    if cfg!(debug_assertions) {
        return false;
    }

    let cargo_profile = Path::new(env!("PIXELPRESENCE_CARGO_PROFILE_DIR"));
    env::current_exe()
        .ok()
        .is_some_and(|executable| !running_from_cargo_profile(&executable, cargo_profile))
}

fn build_tray(app: &AppHandle) -> tauri::Result<()> {
    // Cargo binaries live directly in their debug/release profile directory.
    // An installed bundle copies the executable elsewhere; only that copy can
    // register a durable login entry.
    let installed_build = installed_build();
    let autostart_label = if installed_build {
        "Start with Windows"
    } else {
        "Start with Windows (installed builds only)"
    };
    let autostart_on = app.autolaunch().is_enabled().unwrap_or(false);

    let toggle_item = MenuItem::with_id(app, "toggle", "Show / Hide", true, None::<&str>)?;
    let autostart_item = CheckMenuItem::with_id(
        app,
        "autostart",
        autostart_label,
        installed_build,
        autostart_on,
        None::<&str>,
    )?;
    let quit_item = MenuItem::with_id(app, "quit", "Quit PixelPresence", true, None::<&str>)?;
    let menu = Menu::with_items(app, &[&toggle_item, &autostart_item, &quit_item])?;

    let mut builder = TrayIconBuilder::with_id("pixelpresence")
        .menu(&menu)
        .show_menu_on_left_click(false)
        .tooltip("PixelPresence");

    if let Some(icon) = app.default_window_icon().cloned() {
        builder = builder.icon(icon);
    }

    let autostart_for_handler = autostart_item.clone();

    builder
        .on_menu_event(move |app, event| match event.id().as_ref() {
            "toggle" => toggle_companion(app),
            "autostart" => {
                // The registry is the source of truth, not the tick, so a
                // failure to write it cannot leave the menu lying.
                let manager = app.autolaunch();
                let enabled = manager.is_enabled().unwrap_or(false);
                let outcome = if enabled {
                    manager.disable()
                } else {
                    manager.enable()
                };

                match outcome {
                    Ok(()) => {
                        let now = manager.is_enabled().unwrap_or(!enabled);
                        let _ = autostart_for_handler.set_checked(now);
                    }
                    Err(error) => {
                        eprintln!("pixelpresence: could not change autostart: {error}");
                    }
                }
            }
            "quit" => app.exit(0),
            _ => {}
        })
        .on_tray_icon_event(|tray, event| {
            if let TrayIconEvent::Click {
                button: MouseButton::Left,
                button_state: MouseButtonState::Up,
                ..
            } = event
            {
                toggle_companion(tray.app_handle());
            }
        })
        .build(app)?;

    Ok(())
}

/// Watch the session files and forward whatever the companion should show.
///
/// The files are the transport: Hermes runs in WSL and cannot reach a Windows
/// loopback listener, while both sides can read this directory. One file per
/// session is what lets several agents report at once instead of overwriting a
/// single shared state file.
fn watch_sessions(window: WebviewWindow) {
    thread::spawn(move || {
        let directory = sessions_dir();
        let ttl_seconds = session_ttl_seconds();
        let mut delivered = String::new();

        loop {
            let payload = pick(load_candidates(&directory, ttl_seconds))
                .map(|candidate| candidate.value)
                .unwrap_or_else(resting_event);

            // Only forward a change of what the companion would show, so a
            // second session reporting the same state is not a repaint.
            let text = payload.to_string();
            if text != delivered {
                let _ = window.emit("companion://state", payload);
                delivered = text;
            }

            thread::sleep(POLL_INTERVAL);
        }
    });
}

#[tauri::command]
fn quit_app(app: tauri::AppHandle) {
    app.exit(0);
}

/// The frontend calls this while its context menu is open, so the menu stays
/// clickable even where it extends past the character.
#[tauri::command]
fn set_menu_open(open: bool) {
    FORCED_INTERACTIVE.store(open, Ordering::Relaxed);
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let toggle_shortcut = Shortcut::new(Some(Modifiers::CONTROL | Modifiers::SHIFT), Code::Space);
    let quit_shortcut = Shortcut::new(Some(Modifiers::CONTROL | Modifiers::SHIFT), Code::KeyQ);
    let handler_toggle = toggle_shortcut.clone();
    let handler_quit = quit_shortcut.clone();

    tauri::Builder::default()
        .plugin(tauri_plugin_autostart::init(
            MacosLauncher::LaunchAgent,
            None,
        ))
        .plugin(
            tauri_plugin_global_shortcut::Builder::new()
                .with_handler(move |app, shortcut, event| {
                    if event.state() != ShortcutState::Pressed {
                        return;
                    }

                    if shortcut == &handler_toggle {
                        toggle_companion(app);
                    } else if shortcut == &handler_quit {
                        app.exit(0);
                    }
                })
                .build(),
        )
        .plugin(tauri_plugin_opener::init())
        .invoke_handler(tauri::generate_handler![quit_app, set_menu_open])
        .setup(move |app| {
            let window = app.get_webview_window("main").expect("main window missing");
            place_window(&window)?;
            remember_moves(window.clone());
            build_tray(app.handle())?;
            watch_pointer(window.clone());
            app.global_shortcut().register(toggle_shortcut.clone())?;
            app.global_shortcut().register(quit_shortcut.clone())?;
            watch_sessions(window);
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running PixelPresence");
}

#[cfg(test)]
mod tests {
    use super::*;

    fn candidate(state: &str, timestamp: &str) -> Candidate {
        let value = serde_json::json!({
            "version": PROTOCOL_VERSION,
            "type": "agent.state",
            "agent": "test",
            "state": state,
            "label": null,
            "session_id": state,
            "timestamp": timestamp,
        });
        parse_candidate(&value.to_string()).expect("fixture should parse")
    }

    #[test]
    fn needs_the_user_outranks_merely_busy() {
        let picked = pick(vec![
            candidate("working", "2026-09-21T10:00:05+00:00"),
            candidate("waiting", "2026-09-21T10:00:01+00:00"),
        ])
        .expect("a winner");

        assert_eq!(picked.value["state"], "waiting");
    }

    #[test]
    fn urgency_order_is_the_documented_one() {
        let mut states = STATE_PRIORITY.to_vec();
        let mut picked = Vec::new();
        while !states.is_empty() {
            let champ = pick(
                states
                    .iter()
                    .map(|state| candidate(state, "2026-09-21T10:00:00+00:00"))
                    .collect(),
            )
            .expect("a winner");
            let name = champ.value["state"].as_str().unwrap().to_string();
            picked.push(name.clone());
            states.retain(|state| *state != name);
        }

        assert_eq!(picked, STATE_PRIORITY.to_vec());
    }

    #[test]
    fn most_recent_report_wins_within_a_rank() {
        let picked = pick(vec![
            candidate("working", "2026-09-21T10:00:01+00:00"),
            candidate("working", "2026-09-21T10:00:09+00:00"),
        ])
        .expect("a winner");

        assert_eq!(reported_at(&picked), "2026-09-21T10:00:09+00:00");
    }

    #[test]
    fn an_unknown_state_is_refused() {
        assert!(parse_candidate(r#"{"version":1,"state":"pondering"}"#).is_none());
    }

    #[test]
    fn a_future_protocol_version_is_refused() {
        assert!(parse_candidate(r#"{"version":2,"state":"working"}"#).is_none());
    }

    #[test]
    fn malformed_bodies_and_missing_versions_are_refused() {
        assert!(parse_candidate("not json").is_none());
        assert!(parse_candidate(r#"{"state":"working"}"#).is_none());
    }

    #[test]
    fn no_sessions_rests() {
        assert!(pick(Vec::new()).is_none());
        assert_eq!(resting_event()["state"], "idle");
    }

    #[test]
    fn cargo_profile_executable_is_not_an_installed_build() {
        let profile = Path::new("C:/build/cargo-target/release");
        let executable = profile.join("pixel-presence.exe");
        assert!(running_from_cargo_profile(&executable, profile));
    }

    #[test]
    fn installed_executable_is_not_mistaken_for_cargo_output() {
        let profile = Path::new("C:/build/cargo-target/release");
        let executable =
            Path::new("C:/Users/example/AppData/Local/PixelPresence/pixel-presence.exe");
        assert!(!running_from_cargo_profile(executable, profile));
    }

    #[test]
    fn the_resting_event_is_byte_stable() {
        // A timestamp here would make every poll look like a change.
        assert_eq!(resting_event().to_string(), resting_event().to_string());
    }
}
