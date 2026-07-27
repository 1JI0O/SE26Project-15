use std::{
    io::{BufRead, BufReader},
    net::TcpStream,
    path::Path,
    process::{Child, Command, Stdio},
    sync::{Arc, Mutex},
    thread,
    time::Duration,
};

use tauri::{Manager, WindowEvent};
use tauri_plugin_dialog::{DialogExt, MessageDialogKind};

struct BackendProcess(Mutex<Option<Child>>);

const CLOUD_CREDENTIAL_SERVICE: &str = "com.se26project.tracelab.cloud";
const CLOUD_CREDENTIAL_USER: &str = "refresh-token";

fn cloud_credential() -> Result<keyring::Entry, String> {
    keyring::Entry::new(CLOUD_CREDENTIAL_SERVICE, CLOUD_CREDENTIAL_USER)
        .map_err(|error| error.to_string())
}

#[tauri::command]
fn store_cloud_refresh_token(token: String) -> Result<(), String> {
    cloud_credential()?
        .set_password(&token)
        .map_err(|error| error.to_string())
}

#[tauri::command]
fn load_cloud_refresh_token() -> Result<Option<String>, String> {
    match cloud_credential()?.get_password() {
        Ok(token) => Ok(Some(token)),
        Err(keyring::Error::NoEntry) => Ok(None),
        Err(error) => Err(error.to_string()),
    }
}

#[tauri::command]
fn delete_cloud_refresh_token() -> Result<(), String> {
    match cloud_credential()?.delete_credential() {
        Ok(()) | Err(keyring::Error::NoEntry) => Ok(()),
        Err(error) => Err(error.to_string()),
    }
}

fn report_startup_error<R: tauri::Runtime>(
    app: &tauri::App<R>,
    data_dir: &Path,
    detail: impl AsRef<str>,
) -> tauri::Result<()> {
    let message = format!(
        "TraceLab 内置后端启动失败。\n\n{}\n\n详细信息已写入应用数据目录的 startup-error.log。",
        detail.as_ref()
    );
    let _ = std::fs::write(data_dir.join("startup-error.log"), &message);
    if let Some(window) = app.get_webview_window("main") {
        window.show()?;
    }
    let app_handle = app.handle().clone();
    app.dialog()
        .message(message)
        .title("TraceLab 启动失败")
        .kind(MessageDialogKind::Error)
        .show(move |_| app_handle.exit(1));
    Ok(())
}

fn stop_backend<R: tauri::Runtime>(app: &tauri::AppHandle<R>) {
    if let Some(process) = app.try_state::<BackendProcess>() {
        if let Ok(mut guard) = process.0.lock() {
            if let Some(child) = guard.take() {
                let mut child = child;
                let _ = child.kill();
                let _ = child.wait();
            }
        };
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![
            store_cloud_refresh_token,
            load_cloud_refresh_token,
            delete_cloud_refresh_token
        ])
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_fs::init())
        .plugin(tauri_plugin_pty::init())
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
            let runtime_dir = app.path().resource_dir()?.join("backend-runtime");
            let executable_name = if cfg!(windows) {
                "tracelab-backend.exe"
            } else {
                "tracelab-backend"
            };
            let mut backend_command = Command::new(runtime_dir.join(executable_name));
            backend_command
                .current_dir(&runtime_dir)
                .env("TRACELAB_APP_DATA_DIR", data_dir.as_os_str())
                .env("TRACELAB_BACKEND_PORT", "8765")
                .env("TRACELAB_PARENT_PID", std::process::id().to_string())
                .stdout(Stdio::null())
                .stderr(Stdio::piped());
            let mut child = match backend_command.spawn() {
                Ok(child) => child,
                Err(error) => {
                    report_startup_error(app, &data_dir, error.to_string())?;
                    return Ok(());
                }
            };
            let child_stderr = child.stderr.take();
            app.manage(BackendProcess(Mutex::new(Some(child))));

            let backend_error = Arc::new(Mutex::new(String::new()));
            let error_reader = child_stderr.map(|stderr| {
                let event_backend_error = Arc::clone(&backend_error);
                thread::spawn(move || {
                    for line in BufReader::new(stderr).lines().map_while(Result::ok) {
                        log::error!("backend: {line}");
                        if let Ok(mut error) = event_backend_error.lock() {
                            // Keep the beginning of the traceback (where the
                            // actual exception lives) but cap the diagnostic so
                            // a noisy child cannot fill the application volume.
                            if error.len() < 128 * 1024 {
                                error.push_str(&line);
                                error.push('\n');
                            }
                        }
                    }
                })
            });

            let mut ready = false;
            for _ in 0..600 {
                if TcpStream::connect("127.0.0.1:8765").is_ok() {
                    ready = true;
                    break;
                }
                let backend_exited = app
                    .state::<BackendProcess>()
                    .0
                    .lock()
                    .ok()
                    .and_then(|mut process| {
                        process
                            .as_mut()
                            .and_then(|child| child.try_wait().ok().flatten())
                    })
                    .is_some();
                if backend_exited {
                    break;
                }
                thread::sleep(Duration::from_millis(100));
            }
            if !ready {
                if let Some(error_reader) = error_reader {
                    let _ = error_reader.join();
                }
                let detail = backend_error
                    .lock()
                    .ok()
                    .map(|error| error.trim().to_string())
                    .filter(|error| !error.is_empty())
                    .unwrap_or_else(|| "内置后端未能在 60 秒内启动。".to_string());
                report_startup_error(app, &data_dir, detail)?;
                return Ok(());
            }
            let _ = std::fs::remove_file(data_dir.join("startup-error.log"));
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
