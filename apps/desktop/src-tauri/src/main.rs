// Prevents an extra console window on Windows in release builds
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::sync::Mutex;

use tauri::{AppHandle, Emitter, Manager, PhysicalPosition, RunEvent, WindowEvent};
use tauri_plugin_global_shortcut::{Code, GlobalShortcutExt, Modifiers, Shortcut, ShortcutState};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

/// Port of the Python engine's WebSocket server; the UI connects to ws://127.0.0.1:<port>/ws.
const ENGINE_PORT: &str = "8765";

/// The bundled Python engine process, stopped when the app exits.
struct Engine(Mutex<Option<CommandChild>>);

/// Starts the bundled engine (`emiliano-engine server`). If an engine is already running,
/// the new one exits on its single-instance guard and the UI uses the existing one.
/// Set EMILIANO_EXTERNAL_ENGINE=1 to skip it and run `emiliano server` yourself.
fn start_engine(app: &AppHandle) -> Option<CommandChild> {
    if std::env::var_os("EMILIANO_EXTERNAL_ENGINE").is_some() {
        return None;
    }
    let command = match app.shell().sidecar("emiliano-engine") {
        Ok(command) => command.args(["server", "--port", ENGINE_PORT]),
        Err(err) => {
            eprintln!("[emiliano] engine sidecar unavailable: {err}");
            return None;
        }
    };
    match command.spawn() {
        Ok((mut events, child)) => {
            // Drain the engine's output so its pipes never fill up and block it
            tauri::async_runtime::spawn(async move {
                while let Some(event) = events.recv().await {
                    match event {
                        CommandEvent::Stdout(line) | CommandEvent::Stderr(line) => {
                            eprintln!("[engine] {}", String::from_utf8_lossy(&line).trim_end());
                        }
                        CommandEvent::Terminated(status) => {
                            eprintln!("[engine] exited with code {:?}", status.code);
                        }
                        _ => {}
                    }
                }
            });
            Some(child)
        }
        Err(err) => {
            eprintln!("[emiliano] failed to start engine: {err}");
            None
        }
    }
}

/// Docks the main window on the right of the primary screen and stretches the HUD
/// overlay over the whole screen, letting every click pass through to the apps below.
fn place_windows(app: &AppHandle) -> tauri::Result<()> {
    if let Some(dock) = app.get_webview_window("dock") {
        if let Some(monitor) = dock.primary_monitor()? {
            let (origin, screen) = (monitor.position(), monitor.size());
            // Keep the dock inside small or scaled screens, leaving a margin top and bottom
            let margin = (60.0 * monitor.scale_factor()) as u32;
            let mut size = dock.outer_size()?;
            if size.height + margin > screen.height {
                size.height = screen.height.saturating_sub(margin);
                dock.set_size(size)?;
            }
            let x = origin.x + screen.width as i32 - size.width as i32 - 20;
            let y = origin.y + ((screen.height as i32 - size.height as i32) / 2).max(30);
            dock.set_position(PhysicalPosition::new(x, y))?;
        }
    }
    if let Some(overlay) = app.get_webview_window("overlay") {
        if let Some(monitor) = overlay.primary_monitor()? {
            overlay.set_position(*monitor.position())?;
            overlay.set_size(*monitor.size())?;
        }
        overlay.set_ignore_cursor_events(true)?;
    }
    Ok(())
}

/// Stops the engine and everything it started. The PyInstaller build runs as a launcher
/// plus the real Python process, so on Windows the whole process tree is killed;
/// killing only the launcher would leave the engine holding its port.
fn stop_engine(child: CommandChild) {
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        let _ = std::process::Command::new("taskkill")
            .args(["/F", "/T", "/PID", &child.pid().to_string()])
            .creation_flags(CREATE_NO_WINDOW)
            .status();
    }
    let _ = child.kill();
}

fn escape_key() -> Shortcut {
    Shortcut::new(None, Code::Escape)
}

/// Default shortcut that brings up the dock from anywhere. Not Alt+Space: Windows uses it for every
/// window's system menu.
const DEFAULT_SUMMON: &str = "Ctrl+Shift+Space";

/// The summon shortcut: EMILIANO_SUMMON_SHORTCUT (e.g. "Ctrl+Alt+E") if set and valid, else the default.
/// An empty value turns it off.
fn summon_shortcut() -> Option<Shortcut> {
    let wanted =
        std::env::var("EMILIANO_SUMMON_SHORTCUT").unwrap_or_else(|_| DEFAULT_SUMMON.to_string());
    if wanted.trim().is_empty() {
        return None;
    }
    match wanted.parse::<Shortcut>() {
        Ok(shortcut) => Some(shortcut),
        Err(err) => {
            eprintln!("[emiliano] invalid EMILIANO_SUMMON_SHORTCUT {wanted:?} ({err}); using {DEFAULT_SUMMON}");
            DEFAULT_SUMMON.parse().ok()
        }
    }
}

/// Shows the dock and puts the cursor in its message box; if the dock already has focus, hides it.
fn toggle_dock(app: &AppHandle) {
    let Some(dock) = app.get_webview_window("dock") else {
        return;
    };
    let visible = dock.is_visible().unwrap_or(false) && !dock.is_minimized().unwrap_or(false);
    if visible && dock.is_focused().unwrap_or(false) {
        let _ = dock.hide();
        return;
    }
    let _ = dock.show();
    let _ = dock.unminimize();
    let _ = dock.set_focus();
    let _ = app.emit("summon", ());
}

/// Arms or disarms the system-wide Esc kill switch. The UI arms it only while a task
/// runs, so Esc keeps working normally in other apps the rest of the time.
#[tauri::command]
fn set_kill_switch(app: AppHandle, enabled: bool) -> Result<(), String> {
    let shortcuts = app.global_shortcut();
    let registered = shortcuts.is_registered(escape_key());
    let result = match (enabled, registered) {
        (true, false) => shortcuts.register(escape_key()),
        (false, true) => shortcuts.unregister(escape_key()),
        _ => Ok(()),
    };
    result.map_err(|e| e.to_string())
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(
            tauri_plugin_global_shortcut::Builder::new()
                .with_handler(|app, shortcut, event| {
                    if event.state() != ShortcutState::Pressed {
                        return;
                    }
                    if shortcut.matches(Modifiers::empty(), Code::Escape) {
                        let _ = app.emit("emergency-stop", ());
                    } else if summon_shortcut().is_some_and(|summon| summon.id() == shortcut.id()) {
                        toggle_dock(app);
                    }
                })
                .build(),
        )
        .invoke_handler(tauri::generate_handler![set_kill_switch])
        // The dock is the app: closing it quits, instead of leaving the invisible overlay running
        .on_window_event(|window, event| {
            if window.label() == "dock" && matches!(event, WindowEvent::CloseRequested { .. }) {
                window.app_handle().exit(0);
            }
        })
        .setup(|app| {
            let handle = app.handle();
            app.manage(Engine(Mutex::new(start_engine(handle))));
            place_windows(handle)?;
            // Registered for the app's whole life; failing (another app owns the keys) must not stop startup
            if let Some(summon) = summon_shortcut() {
                if let Err(err) = app.global_shortcut().register(summon) {
                    eprintln!("[emiliano] could not register the summon shortcut: {err}");
                }
            }
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building Emiliano")
        .run(|app, event| {
            if let RunEvent::Exit = event {
                let child = app
                    .state::<Engine>()
                    .0
                    .lock()
                    .ok()
                    .and_then(|mut engine| engine.take());
                if let Some(child) = child {
                    stop_engine(child);
                }
            }
        });
}
