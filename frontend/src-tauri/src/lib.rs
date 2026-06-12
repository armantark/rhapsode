use std::net::TcpListener;
use std::path::PathBuf;
use std::sync::Mutex;
use std::thread;
use std::time::Duration;

use tauri::{Manager, RunEvent, State};
use tauri_plugin_shell::process::CommandChild;
use tauri_plugin_shell::ShellExt;

struct BackendState {
    api_base_url: String,
    child: Mutex<Option<CommandChild>>,
}

#[tauri::command]
fn api_base_url(state: State<'_, BackendState>) -> String {
    state.api_base_url.clone()
}

fn reserve_port() -> Result<u16, String> {
    TcpListener::bind("127.0.0.1:0")
        .map_err(|error| format!("failed to reserve localhost port: {error}"))
        .and_then(|listener| {
            listener
                .local_addr()
                .map(|address| address.port())
                .map_err(|error| format!("failed to read reserved port: {error}"))
        })
}

fn wait_for_health(port: u16) -> Result<(), String> {
    let url = format!("http://127.0.0.1:{port}/api/v1/health");
    for attempt in 0..120 {
        match ureq::get(&url).call() {
            Ok(response) if response.status() == 200 => return Ok(()),
            Ok(response) => log::warn!(
                "backend health check returned {} (attempt {attempt})",
                response.status()
            ),
            Err(error) if attempt == 0 || attempt % 10 == 0 => {
                log::info!("waiting for backend at {url}: {error}");
            }
            Err(_) => {}
        }
        thread::sleep(Duration::from_millis(500));
    }
    Err(format!("backend health check timed out at {url}"))
}

fn backend_paths(app: &tauri::AppHandle) -> Result<(PathBuf, PathBuf, PathBuf, PathBuf), String> {
    let data_dir = app
        .path()
        .app_data_dir()
        .map_err(|error| format!("failed to resolve app data dir: {error}"))?
        .join("data");
    let media_dir = data_dir.join("media");
    let backup_dir = data_dir.join("backups");
    let db_path = data_dir.join("rhapsode.db");

    std::fs::create_dir_all(&media_dir)
        .map_err(|error| format!("failed to create media dir {}: {error}", media_dir.display()))?;
    std::fs::create_dir_all(&backup_dir).map_err(|error| {
        format!(
            "failed to create backup dir {}: {error}",
            backup_dir.display()
        )
    })?;

    Ok((data_dir, media_dir, backup_dir, db_path))
}

fn spawn_sidecar(
    app: &tauri::AppHandle,
    port: u16,
    data_dir: &PathBuf,
    media_dir: &PathBuf,
    backup_dir: &PathBuf,
    db_path: &PathBuf,
) -> Result<CommandChild, String> {
    let database_url = format!("sqlite:///{}", db_path.display());
    let sidecar = app
        .shell()
        .sidecar("binaries/rhapsode-backend")
        .map_err(|error| format!("failed to locate rhapsode-backend sidecar: {error}"))?;

    let (mut rx, child) = sidecar
        .env("RHAPSODE_PORT", port.to_string())
        .env("RHAPSODE_DESKTOP", "1")
        .env(
            "RHAPSODE_DATA_DIR",
            data_dir.to_string_lossy().into_owned(),
        )
        .env("RHAPSODE_DATABASE_URL", database_url)
        .env(
            "RHAPSODE_MEDIA_DIR",
            media_dir.to_string_lossy().into_owned(),
        )
        .env(
            "RHAPSODE_BACKUP_DIR",
            backup_dir.to_string_lossy().into_owned(),
        )
        .spawn()
        .map_err(|error| format!("failed to spawn rhapsode-backend sidecar: {error}"))?;

    tauri::async_runtime::spawn(async move {
        while rx.recv().await.is_some() {}
    });

    Ok(child)
}

fn start_backend(app: &tauri::AppHandle) -> Result<BackendState, String> {
    let (data_dir, media_dir, backup_dir, db_path) = backend_paths(app)?;
    let reserved_port = reserve_port()?;

    match spawn_sidecar(
        app,
        reserved_port,
        &data_dir,
        &media_dir,
        &backup_dir,
        &db_path,
    ) {
        Ok(child) => {
            wait_for_health(reserved_port)?;
            Ok(BackendState {
                api_base_url: format!("http://127.0.0.1:{reserved_port}/api/v1"),
                child: Mutex::new(Some(child)),
            })
        }
        Err(error) if cfg!(debug_assertions) => {
            let fallback_port = 8000u16;
            log::warn!(
                "{error}; falling back to external backend at http://127.0.0.1:{fallback_port}/api/v1"
            );
            wait_for_health(fallback_port)?;
            Ok(BackendState {
                api_base_url: format!("http://127.0.0.1:{fallback_port}/api/v1"),
                child: Mutex::new(None),
            })
        }
        Err(error) => Err(error),
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .setup(|app| {
            if cfg!(debug_assertions) {
                app.handle().plugin(
                    tauri_plugin_log::Builder::default()
                        .level(log::LevelFilter::Info)
                        .build(),
                )?;
            }

            let backend = start_backend(app.handle())?;
            app.manage(backend);
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![api_base_url])
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app_handle, event| {
            if let RunEvent::Exit = event {
                if let Some(state) = app_handle.try_state::<BackendState>() {
                    if let Ok(mut guard) = state.child.lock() {
                        if let Some(child) = guard.take() {
                            let _ = child.kill();
                        }
                    }
                }
            }
        });
}
