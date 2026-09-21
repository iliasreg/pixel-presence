use std::fs;
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::Duration;

use tauri::menu::{Menu, MenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{AppHandle, Emitter, Manager, PhysicalPosition, WebviewWindow};
use tauri_plugin_global_shortcut::{Code, GlobalShortcutExt, Modifiers, Shortcut, ShortcutState};

/// How often the companion re-reads the state file the agent hook writes.
const POLL_INTERVAL: Duration = Duration::from_millis(250);

/// How often the pointer is tested against the character. A window that is
/// ignoring cursor events cannot report that the pointer arrived, so the
/// position has to be polled rather than listened for.
const HIT_TEST_INTERVAL: Duration = Duration::from_millis(60);

/// How often a dragged position is committed to disk. Dragging emits a move
/// event per frame, so the writes are batched instead of hitting the disk.
const POSITION_FLUSH_INTERVAL: Duration = Duration::from_millis(1000);

/// Character geometry in CSS pixels, mirroring `.pixel-pet` in styles.css.
/// Everything outside this box is transparent, so a click there belongs to
/// whatever is behind the companion.
const PET_SIZE: f64 = 192.0;
const PET_RIGHT: f64 = 20.0;
const PET_BOTTOM: f64 = 18.0;

/// Set while a menu is open. Menus can extend past the character, and in a
/// click-through window the item under the pointer would be unreachable.
static FORCED_INTERACTIVE: AtomicBool = AtomicBool::new(false);

fn state_file_override() -> Option<PathBuf> {
    std::env::var_os("PIXELPRESENCE_STATE_FILE").map(PathBuf::from)
}

fn home_dir() -> PathBuf {
    std::env::var_os("USERPROFILE")
        .or_else(|| std::env::var_os("HOME"))
        .map(PathBuf::from)
        .expect("no home directory to resolve the companion state file")
}

/// Directory both sides use for companion state. Overriding the state file
/// moves its siblings with it, so a redirected setup stays self-contained.
fn state_dir() -> PathBuf {
    if let Some(parent) = state_file_override().and_then(|path| path.parent().map(PathBuf::from)) {
        return parent;
    }
    home_dir().join(".pixelpresence")
}

fn state_file() -> PathBuf {
    state_file_override().unwrap_or_else(|| state_dir().join("state.json"))
}

/// Where the dragged window position is remembered. Separate from the state
/// file, which the agent hook rewrites on every event.
fn window_state_file() -> PathBuf {
    state_dir().join("window.json")
}

fn load_remembered_position() -> Option<PhysicalPosition<i32>> {
    let text = fs::read_to_string(window_state_file()).ok()?;
    let value: serde_json::Value = serde_json::from_str(&text).ok()?;
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

fn build_tray(app: &AppHandle) -> tauri::Result<()> {
    let toggle = MenuItem::with_id(app, "toggle", "Show / Hide", true, None::<&str>)?;
    let quit = MenuItem::with_id(app, "quit", "Quit PixelPresence", true, None::<&str>)?;
    let menu = Menu::with_items(app, &[&toggle, &quit])?;

    let mut builder = TrayIconBuilder::with_id("pixelpresence")
        .menu(&menu)
        .show_menu_on_left_click(false)
        .tooltip("PixelPresence");

    if let Some(icon) = app.default_window_icon().cloned() {
        builder = builder.icon(icon);
    }

    builder
        .on_menu_event(|app, event| match event.id().as_ref() {
            "toggle" => toggle_companion(app),
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

/// Watch the agent state file and forward each new event to the frontend.
///
/// The file is the transport: Hermes runs in WSL and cannot reach a Windows
/// loopback listener, while both sides can read this path.
fn watch_state_file(window: WebviewWindow) {
    thread::spawn(move || {
        let path = state_file();
        let mut delivered = String::new();

        loop {
            if let Ok(text) = fs::read_to_string(&path) {
                if text != delivered {
                    match serde_json::from_str::<serde_json::Value>(&text) {
                        Ok(event) => {
                            let _ = window.emit("companion://state", event);
                        }
                        Err(_) => {}
                    }
                    // An unparseable payload is only retried once it changes.
                    delivered = text;
                }
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
            watch_state_file(window);
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running PixelPresence");
}
