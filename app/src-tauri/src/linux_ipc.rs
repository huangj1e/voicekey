//! Per-user control socket for Omarchy's dictation adapter.
use crate::hotkey::{HotEvent, Shared};
use std::{io::{Read, Write}, os::unix::{fs::PermissionsExt, net::UnixListener}, sync::{atomic::Ordering, Arc}};
use tokio::sync::mpsc::UnboundedSender;

pub fn start(tx: UnboundedSender<HotEvent>, shared: Arc<Shared>) {
    let Some(dir) = std::env::var_os("XDG_RUNTIME_DIR") else { eprintln!("voicekey: XDG_RUNTIME_DIR is unavailable"); return };
    let path = std::path::PathBuf::from(dir).join("voicekey.sock");
    if std::os::unix::net::UnixStream::connect(&path).is_ok() { return; }
    let _ = std::fs::remove_file(&path);
    let listener = match UnixListener::bind(&path) { Ok(v) => v, Err(e) => { eprintln!("voicekey: cannot create control socket: {e}"); return; } };
    let _ = std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600));
    std::thread::spawn(move || {
        for mut conn in listener.incoming().flatten() {
            let _ = conn.set_read_timeout(Some(std::time::Duration::from_secs(1)));
            let mut buffer = [0u8; 32];
            let n = conn.read(&mut buffer).unwrap_or(0);
            let result = if shared.paused.load(Ordering::Relaxed) { "paused\n" } else {
                match std::str::from_utf8(&buffer[..n]).unwrap_or("").trim() {
                    "start" => { let _ = tx.send(HotEvent::Press); let _ = tx.send(HotEvent::LongPress); "ok\n" },
                    "stop" => { let _ = tx.send(HotEvent::Release); "ok\n" },
                    "toggle" => { let _ = tx.send(HotEvent::Tap); "ok\n" },
                    _ => "invalid\n",
                }
            };
            let _ = conn.write_all(result.as_bytes());
        }
    });
}
