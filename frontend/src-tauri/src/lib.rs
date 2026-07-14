use std::{net::TcpStream, sync::Mutex, thread, time::Duration};

use tauri::{Manager, WindowEvent};
use tauri_plugin_shell::{
    process::{CommandChild, CommandEvent},
    ShellExt,
};

struct BackendProcess(Mutex<Option<CommandChild>>);

fn stop_backend<R: tauri::Runtime>(app: &tauri::AppHandle<R>) {
    if let Some(process) = app.try_state::<BackendProcess>() {
        if let Ok(mut guard) = process.0.lock() {
            if let Some(child) = guard.take() {
                let _ = child.kill();
            }
        };
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_fs::init())
        .plugin(tauri_plugin_shell::init())
        .setup(|app| {
            if cfg!(debug_assertions) {
                app.handle().plugin(
                    tauri_plugin_log::Builder::default()
                        .level(log::LevelFilter::Info)
                        .build(),
                )?;
            }

            let data_dir = app.path().app_data_dir()?;
            std::fs::create_dir_all(&data_dir)?;
            let (mut events, child) = app
                .shell()
                .sidecar("tracelab-backend")?
                .env("TRACELAB_APP_DATA_DIR", data_dir.as_os_str())
                .env("TRACELAB_BACKEND_PORT", "8765")
                .env("TRACELAB_PARENT_PID", std::process::id().to_string())
                .spawn()?;
            app.manage(BackendProcess(Mutex::new(Some(child))));

            tauri::async_runtime::spawn(async move {
                while let Some(event) = events.recv().await {
                    match event {
                        CommandEvent::Stdout(line) => {
                            log::info!("backend: {}", String::from_utf8_lossy(&line));
                        }
                        CommandEvent::Stderr(line) => {
                            log::error!("backend: {}", String::from_utf8_lossy(&line));
                        }
                        CommandEvent::Terminated(payload) => {
                            log::info!("backend stopped: {:?}", payload.code);
                        }
                        _ => {}
                    }
                }
            });

            let mut ready = false;
            for _ in 0..600 {
                if TcpStream::connect("127.0.0.1:8765").is_ok() {
                    ready = true;
                    break;
                }
                thread::sleep(Duration::from_millis(100));
            }
            if !ready {
                return Err("TraceLab backend did not become ready within 60 seconds".into());
            }
            if let Some(window) = app.get_webview_window("main") {
                window.show()?;
            }
            Ok(())
        })
        .on_window_event(|window, event| {
            if let WindowEvent::Destroyed = event {
                stop_backend(window.app_handle());
            }
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application");

    app.run(|app_handle, event| {
        if matches!(
            event,
            tauri::RunEvent::Exit | tauri::RunEvent::ExitRequested { .. }
        ) {
            stop_backend(app_handle);
        }
    });
}
