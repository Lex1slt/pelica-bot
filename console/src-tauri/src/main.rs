#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]
// Pelica Console 壳：经 tauri-plugin-shell 启动网关 sidecar（插件内部走
// 固定二进制 + 参数列表、Windows 下自动 CREATE_NO_WINDOW，不经过 shell）。
// 托盘三态、关闭=最小化到托盘、开机自启。

use std::io::{Read, Write};
use std::net::TcpStream;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Mutex;
use std::time::Duration;

use serde::Serialize;
use tauri::{
    AppHandle, Emitter, Manager,
    menu::{Menu, MenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    WindowEvent,
};
use tauri_plugin_shell::process::CommandEvent;
use tauri_plugin_shell::ShellExt;

#[derive(Clone, Serialize, Default)]
struct GatewayInfo {
    port: u16,
    token: String,
    alive: bool,
    mode: String, // packaged | dev
}

struct ShellState {
    gateway: Mutex<GatewayInfo>,
    quitting: Mutex<bool>,
    generation: Mutex<u64>,
    children: Mutex<Vec<tauri_plugin_shell::process::CommandChild>>,
    /// 壳视角的机器人运行态（由前端 set_tray 同步；托盘菜单据此启停）
    bot_running: AtomicBool,
    /// 托盘菜单「启停机器人」项（动态文本）
    toggle_item: Mutex<Option<tauri::menu::MenuItem<tauri::Wry>>>,
}

/// 壳内直连网关的极简 HTTP POST（本机、无 TLS、空 body；不依赖前端存活）。
fn gateway_post(info: &GatewayInfo, path: &str) -> Result<(), String> {
    let addr = format!("127.0.0.1:{}", info.port);
    let mut stream = TcpStream::connect(&addr).map_err(|e| format!("connect: {e}"))?;
    stream
        .set_read_timeout(Some(Duration::from_secs(8)))
        .map_err(|e| e.to_string())?;
    let req = format!(
        "POST {} HTTP/1.1\r\nHost: {}\r\nAuthorization: Bearer {}\r\nContent-Length: 0\r\nConnection: close\r\n\r\n",
        path, addr, info.token
    );
    stream
        .write_all(req.as_bytes())
        .map_err(|e| format!("write: {e}"))?;
    let mut buf = [0u8; 256];
    let _ = stream.read(&mut buf);
    Ok(())
}

#[tauri::command]
fn get_gateway(state: tauri::State<ShellState>) -> GatewayInfo {
    state.gateway.lock().unwrap().clone()
}

#[tauri::command]
fn set_tray(app: AppHandle, mode: String) {
    let state = app.state::<ShellState>();
    state
        .bot_running
        .store(mode == "running", Ordering::Relaxed);
    // 动态菜单项文本：运行中→可停止；未运行→可启动
    if let Some(item) = state.toggle_item.lock().unwrap().as_ref() {
        let _ = item.set_text(if mode == "running" {
            "停止机器人"
        } else {
            "启动机器人"
        });
    }
    set_tray_icon(&app, &mode);
}

#[tauri::command]
fn enable_autostart(app: AppHandle, enable: bool) -> Result<(), String> {
    use tauri_plugin_autostart::ManagerExt;
    let mgr = app.autolaunch();
    if enable {
        mgr.enable().map_err(|e| e.to_string())
    } else {
        mgr.disable().map_err(|e| e.to_string())
    }
}

#[tauri::command]
fn restart_gateway(app: AppHandle) -> Result<GatewayInfo, String> {
    spawn_gateway(&app)
}

fn set_tray_icon(app: &AppHandle, mode: &str) {
    let icon = match mode {
        "running" => "icons/tray-running.png",
        "silent" => "icons/tray-silent.png",
        _ => "icons/tray-offline.png",
    };
    if let Some(tray) = app.tray_by_id("main") {
        let resolved = app
            .path()
            .resolve(icon, tauri::path::BaseDirectory::Resource)
            .unwrap_or_else(|_| icon.into());
        let decoded = image::ImageReader::open(&resolved)
            .ok()
            .and_then(|r| r.decode().ok())
            .map(|d| d.to_rgba8());
        if let Some(decoded) = decoded {
            let (w, h) = decoded.dimensions();
            let img = tauri::image::Image::new_owned(decoded.into_raw(), w, h);
            let _ = tray.set_icon(Some(img));
        }
        let _ = tray.set_tooltip(Some(match mode {
            "running" => "Pelica Console · 运行中",
            "silent" => "Pelica Console · 静默（机器人未运行）",
            _ => "Pelica Console · 网关离线",
        }));
    }
}

fn debug_log(line: &str) {
    // 排障用：写入用户数据目录（仅错误路径调用）
    if let Ok(appdata) = std::env::var("APPDATA") {
        let dir = std::path::PathBuf::from(appdata).join("pelica-console");
        let _ = std::fs::create_dir_all(&dir);
        let _ = std::fs::write(
            dir.join("shell-debug.log"),
            format!("{:?}: {line}\n", std::time::SystemTime::now()),
        );
    }
}

/// 启动网关子进程并监听 stdout 握手行（PELICA_GATEWAY_READY {port,token}）。
fn spawn_gateway(app: &AppHandle) -> Result<GatewayInfo, String> {
    let state = app.state::<ShellState>();
    let generation = {
        let mut g = state.generation.lock().unwrap();
        *g += 1;
        *g
    };

    let resource_dir = app
        .path()
        .resource_dir()
        .map_err(|e| {
            let msg = format!("resource dir: {e}");
            debug_log(&msg);
            msg
        })?;
    let packaged_exe = resource_dir
        .join("gateway-dist")
        .join("pelica-gateway")
        .join("pelica-gateway.exe");
    // 开发模式回退：仓库 .venv 直跑（控制台.bat 之外的本壳调试形态）
    let repo_root = std::env::current_dir()
        .map(|d| d.join("../..").canonicalize().unwrap_or(d.join("../..")))
        .unwrap_or_default();
    let dev_python = repo_root.join(".venv/Scripts/python.exe");

    let (exe, cwd, args): (std::path::PathBuf, std::path::PathBuf, Vec<String>) =
        if packaged_exe.exists() {
            (packaged_exe, resource_dir.clone(), Vec::new())
        } else if dev_python.exists() {
            (
                dev_python,
                repo_root.clone(),
                vec!["-m".to_string(), "gateway".to_string()],
            )
        } else {
            let msg = format!(
                "未找到网关：packaged={:?} dev={:?}",
                packaged_exe, dev_python
            );
            debug_log(&msg);
            return Err("未找到网关（gateway-dist 缺失且非开发环境）".into());
        };
    let is_packaged = exe.extension().map(|e| e == "exe").unwrap_or(false);

    // 插件 Command 默认把 stdout 以 CommandEvent::Stdout 事件流送回（无需配置 Stdio）
    let command = app.shell().command(exe).args(args).current_dir(cwd);

    let (mut rx, child) = match command.spawn() {
        Ok(v) => v,
        Err(e) => {
            let msg = format!("spawn: {e}");
            debug_log(&msg);
            return Err(msg);
        }
    };
    state.children.lock().unwrap().push(child);

    let app_handle = app.clone();
    std::thread::spawn(move || {
        while let Some(event) = rx.blocking_recv() {
            if generation != *app_handle.state::<ShellState>().generation.lock().unwrap() {
                return; // 已有更新一代的网关在跑，本代静默退出
            }
            if let CommandEvent::Stdout(line) = event {
                const PREFIX: &[u8] = b"PELICA_GATEWAY_READY ";
                if line.starts_with(PREFIX) {
                    if let Ok(text) = std::str::from_utf8(&line[PREFIX.len()..]) {
                        if let Ok(v) = serde_json::from_str::<serde_json::Value>(text) {
                            let info = GatewayInfo {
                                port: v["port"].as_u64().unwrap_or(0) as u16,
                                token: v["token"].as_str().unwrap_or("").to_string(),
                                alive: true,
                                mode: if is_packaged {
                                    "packaged".into()
                                } else {
                                    "dev".into()
                                },
                            };
                            *app_handle.state::<ShellState>().gateway.lock().unwrap() =
                                info.clone();
                            let _ = app_handle.emit("gateway-ready", &info);
                        }
                    }
                }
            }
        }
        // 事件流结束 = 网关进程退出
        let st = app_handle.state::<ShellState>();
        if generation == *st.generation.lock().unwrap() {
            let mut gw = st.gateway.lock().unwrap();
            gw.alive = false;
            let offline = gw.clone();
            drop(gw);
            set_tray_icon(&app_handle, "offline");
            let _ = app_handle.emit("gateway-down", &offline);
        }
    });

    Err("网关启动中，握手后可通过 get_gateway 获取连接信息。".into())
}

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_autostart::init(
            tauri_plugin_autostart::MacosLauncher::LaunchAgent,
            None,
        ))
        .manage(ShellState {
            gateway: Mutex::new(GatewayInfo::default()),
            quitting: Mutex::new(false),
            generation: Mutex::new(0),
            children: Mutex::new(Vec::new()),
            bot_running: AtomicBool::new(false),
            toggle_item: Mutex::new(None),
        })
        .invoke_handler(tauri::generate_handler![
            get_gateway,
            set_tray,
            enable_autostart,
            restart_gateway
        ])
        .setup(|app| {
            let show = MenuItem::with_id(app, "show", "显示主窗口", true, None::<&str>)?;
            let toggle =
                MenuItem::with_id(app, "toggle_bot", "启动机器人", true, None::<&str>)?;
            let open_data =
                MenuItem::with_id(app, "open_data", "打开数据目录", true, None::<&str>)?;
            let sep = tauri::menu::PredefinedMenuItem::separator(app)?;
            let quit = MenuItem::with_id(app, "quit", "退出 Pelica Console", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&show, &toggle, &open_data, &sep, &quit])?;
            let app_handle = app.handle().clone();
            TrayIconBuilder::with_id("main")
                .menu(&menu)
                .show_menu_on_left_click(false)
                .on_menu_event(move |app, event| {
                    let state = app.state::<ShellState>();
                    match event.id().as_ref() {
                        "show" => {
                            if let Some(win) = app.get_webview_window("main") {
                                let _ = win.show();
                                let _ = win.set_focus();
                            }
                        }
                        "toggle_bot" => {
                            let info = state.gateway.lock().unwrap().clone();
                            if !info.alive {
                                return; // 网关未就绪：菜单动作忽略
                            }
                            let running = state.bot_running.load(Ordering::Relaxed);
                            let path = if running {
                                "/api/core/stop"
                            } else {
                                "/api/core/start"
                            };
                            if let Err(e) = gateway_post(&info, path) {
                                debug_log(&format!("托盘启停失败 {path}: {e}"));
                            }
                        }
                        "open_data" => {
                            if let Ok(appdata) = std::env::var("APPDATA") {
                                let dir =
                                    std::path::PathBuf::from(appdata).join("pelica-console");
                                let _ = std::fs::create_dir_all(&dir);
                                // 固定程序 explorer + 目录参数（无 shell 拼接）
                                let _ = std::process::Command::new("explorer")
                                    .arg(dir)
                                    .spawn();
                            }
                        }
                        "quit" => {
                            *state.quitting.lock().unwrap() = true;
                            app.exit(0);
                        }
                        _ => {}
                    }
                })
                .on_tray_icon_event(|tray, event| {
                    // 左键：显示主窗口；右键菜单由系统按 menu 绑定自动弹出
                    if let TrayIconEvent::Click {
                        button: MouseButton::Left,
                        button_state: MouseButtonState::Up,
                        ..
                    } = event
                    {
                        let app = tray.app_handle();
                        if let Some(win) = app.get_webview_window("main") {
                            let _ = win.show();
                            let _ = win.set_focus();
                        }
                    }
                })
                .build(app)?;
            // 强制把菜单句柄同步进托盘（防创建时序竞态导致右键无菜单）
            if let Some(tray) = app.tray_by_id("main") {
                let _ = tray.set_menu(Some(menu.clone()));
            }
            *app.state::<ShellState>()
                .toggle_item
                .lock()
                .unwrap() = Some(toggle);
            set_tray_icon(&app_handle, "silent");

            // 主窗口关闭 = 最小化到托盘（托盘右键菜单可真正退出）
            let main = app.get_webview_window("main").unwrap();
            let close_handle = app_handle.clone();
            let win_handle = main.clone();
            main.on_window_event(move |event| {
                if let WindowEvent::CloseRequested { api, .. } = event {
                    let quitting =
                        *close_handle.state::<ShellState>().quitting.lock().unwrap();
                    if !quitting {
                        api.prevent_close();
                        let _ = win_handle.hide();
                    }
                }
            });

            let boot_handle = app.handle().clone();
            std::thread::spawn(move || {
                let _ = spawn_gateway(&boot_handle);
            });
            Ok(())
        })
        .on_window_event(|window, event| {
            // 退出前杀掉网关子进程（CommandChild drop 不会终止进程，必须显式 kill）
            if let WindowEvent::Destroyed = event {
                if window.label() == "main" {
                    let app = window.app_handle();
                    let st = app.state::<ShellState>();
                    let taken = std::mem::take(&mut *st.children.lock().unwrap());
                    for child in taken {
                        let _ = child.kill();
                    }
                }
            }
        })
        .run(tauri::generate_context!())
        .expect("pelica console 壳启动失败");
}

fn main() {
    run();
}
