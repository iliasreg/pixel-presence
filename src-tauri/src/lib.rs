use std::fs;
use std::path::PathBuf;
use std::thread;
use std::time::Duration;

use tauri::{Emitter, Manager, PhysicalPosition};
use tauri_plugin_global_shortcut::{Code, GlobalShortcutExt, Modifiers, Shortcut, ShortcutState};

/// How often the companion re-reads the state file the agent hook writes.
const POLL_INTERVAL: Duration = Duration::from_millis(250);

fn state_file() -> PathBuf {
    if let Some(path) = std::env::var_os("PIXELPRESENCE_STATE_FILE") {
        return PathBuf::from(path);
    }

    let home = std::env::var_os("USERPROFILE")
        .or_else(|| std::env::var_os("HOME"))
        .expect("no home directory to resolve the companion state file");

    PathBuf::from(home)
        .join(".pixelpresence")
        .join("state.json")
}

fn position_bottom_right(window: &tauri::WebviewWindow) -> tauri::Result<()> {
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

/// Watch the agent state file and forward each new event to the frontend.
///
/// The file is the transport: Hermes runs in WSL and cannot reach a Windows
/// loopback listener, while both sides can read this path.
fn watch_state_file(window: tauri::WebviewWindow) {
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
                        if let Some(window) = app.get_webview_window("main") {
                            if window.is_visible().unwrap_or(false) {
                                let _ = window.hide();
                            } else {
                                let _ = window.show();
                                let _ = window.set_focus();
                            }
                        }
                    } else if shortcut == &handler_quit {
                        app.exit(0);
                    }
                })
                .build(),
        )
        .plugin(tauri_plugin_opener::init())
        .invoke_handler(tauri::generate_handler![quit_app])
        .setup(move |app| {
            let window = app.get_webview_window("main").expect("main window missing");
            position_bottom_right(&window)?;
            app.global_shortcut().register(toggle_shortcut.clone())?;
            app.global_shortcut().register(quit_shortcut.clone())?;
            watch_state_file(window);
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running PixelPresence");
}
