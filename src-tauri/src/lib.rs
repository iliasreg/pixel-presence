use tauri::{Manager, PhysicalPosition};

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .setup(|app| {
            let window = app.get_webview_window("main").expect("main window missing");

            if let Some(monitor) = window.primary_monitor()? {
                let work_area = monitor.work_area();
                let size = window.outer_size()?;
                let margin = 24;
                let x =
                    work_area.position.x + work_area.size.width as i32 - size.width as i32 - margin;
                let y = work_area.position.y + work_area.size.height as i32
                    - size.height as i32
                    - margin;
                window.set_position(PhysicalPosition::new(x, y))?;
            }

            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running PixelPresence");
}
