use std::fs;
use std::path::PathBuf;
use std::thread;
use std::time::Duration;

use tauri::{Emitter, Manager, PhysicalPosition};

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

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .setup(|app| {
            let window = app.get_webview_window("main").expect("main window missing");
            position_bottom_right(&window)?;
            watch_state_file(window);
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running PixelPresence");
}
