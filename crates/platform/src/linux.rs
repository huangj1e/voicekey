//! Wayland backend for Hyprland: observe evdev keyboards and inject text with wtype.
use crate::{HookFn, KeyEvent, KeyKind, MicStatus, Rect, ALT, CTRL, META, SHIFT};
use crate::volume::OutputVolumeSnapshot;
use std::{collections::HashSet, fs::File, io::Read, path::PathBuf, sync::{Arc, Mutex}, time::Duration};

fn keyboards() -> Vec<PathBuf> {
    std::fs::read_dir("/dev/input/by-path").into_iter().flatten().flatten()
        .map(|e| e.path()).filter(|p| p.to_string_lossy().ends_with("-event-kbd")).collect()
}

pub fn start_hook(f: HookFn) {
    std::thread::spawn(move || {
        let state = Arc::new(Mutex::new((f, HashSet::<u32>::new())));
        let mut seen = HashSet::new();
        loop {
            for path in keyboards() {
                let Ok(real) = path.canonicalize() else { continue };
                if !seen.insert(real.clone()) { continue; }
                let Ok(mut file) = File::open(&real) else { seen.remove(&real); continue };
                let state = state.clone();
                std::thread::spawn(move || loop {
                    // struct input_event has two native longs followed by type, code and value.
                    let mut raw = [0u8; std::mem::size_of::<libc::timeval>() + 8];
                    if file.read_exact(&mut raw).is_err() { break; }
                    let off = std::mem::size_of::<libc::timeval>();
                    let typ = u16::from_ne_bytes([raw[off], raw[off+1]]);
                    if typ != 1 { continue; }
                    let code = u16::from_ne_bytes([raw[off+2], raw[off+3]]) as u32;
                    let value = i32::from_ne_bytes(raw[off+4..off+8].try_into().unwrap());
                    if !(0..=2).contains(&value) { continue; }
                    let mut s = state.lock().unwrap();
                    if value == 0 { s.1.remove(&code); } else { s.1.insert(code); }
                    let mods = [(CTRL, [29,97]), (ALT,[56,100]), (SHIFT,[42,54]), (META,[125,126])]
                        .iter().fold(0, |m, (flag, codes)| m | if codes.iter().any(|c| s.1.contains(c)) { *flag } else { 0 });
                    let kind = if keys::modifier(code).is_some() { KeyKind::Modifier(value != 0) } else if value == 0 { KeyKind::Up } else { KeyKind::Down };
                    let event = KeyEvent { kind, code, mods, repeat: value == 2, chars: keys::character(code).map(str::to_string) };
                    (s.0)(&event); // evdev observation cannot suppress the original event.
                });
            }
            std::thread::sleep(Duration::from_secs(3));
        }
    });
}
fn wtype(args: &[&str]) -> bool {
    match std::process::Command::new("wtype").args(args).status() {
        Ok(status) if status.success() => true,
        result => { eprintln!("voicekey: wtype failed: {result:?}"); false }
    }
}

#[derive(Clone, Debug)]
pub struct FrontApp { address: String }
static TARGET: Mutex<Option<FrontApp>> = Mutex::new(None);

fn active_window() -> Option<serde_json::Value> {
    let output = std::process::Command::new("hyprctl").args(["activewindow", "-j"]).output().ok()?;
    if !output.status.success() { return None; }
    serde_json::from_slice(&output.stdout).ok()
}
fn is_overlay(window: &serde_json::Value) -> bool {
    let title = window["title"].as_str().unwrap_or("");
    let class = window["class"].as_str().unwrap_or("");
    matches!(title, "hud" | "pick") && class.eq_ignore_ascii_case("voicekey")
}
pub fn front_app() -> Option<FrontApp> {
    let window = active_window()?;
    if is_overlay(&window) { return TARGET.lock().unwrap().clone(); }
    let target = FrontApp { address: window["address"].as_str()?.to_owned() };
    eprintln!("voicekey: input target class {:?}, address {}", window["class"].as_str().unwrap_or("unknown"), target.address);
    *TARGET.lock().unwrap() = Some(target.clone());
    Some(target)
}
impl FrontApp {
    pub fn activate(&self) {
        if !self.address.starts_with("0x") || !self.address[2..].chars().all(|c| c.is_ascii_hexdigit()) {
            eprintln!("voicekey: invalid window address");
            return;
        }
        let dispatcher = format!("hl.dsp.focus({{ window = \"address:{}\" }})", self.address);
        match std::process::Command::new("hyprctl").args(["dispatch", &dispatcher]).output() {
            Ok(result) if result.status.success() && String::from_utf8_lossy(&result.stdout).trim() == "ok" => {},
            result => eprintln!("voicekey: could not restore input focus: {result:?}"),
        }
    }
}
fn restore_overlay_focus() -> Option<FrontApp> {
    let target = TARGET.lock().unwrap().clone();
    if let (Some(target), Some(active)) = (&target, active_window()) {
        let own = active["pid"].as_u64() == Some(std::process::id() as u64) || is_overlay(&active);
        if own && active["address"].as_str() != Some(&target.address) {
            target.activate();
            std::thread::sleep(Duration::from_millis(120));
            let focused = active_window();
            if focused.as_ref().and_then(|v| v["address"].as_str()) != Some(&target.address) {
                eprintln!("voicekey: input target did not regain focus");
            }
        }
    }
    target
}
pub fn inject_key(_code: u32, _down: bool) {}
pub(crate) fn backspace(n: usize) {
    if n == 0 { return; }
    restore_overlay_focus();
    let mut command = std::process::Command::new("wtype");
    for _ in 0..n { command.args(["-k", "BackSpace"]); }
    if !command.status().map(|s| s.success()).unwrap_or(false) { eprintln!("voicekey: backspace failed"); }
}
pub(crate) fn type_text(text: &str) { paste(text); }
pub fn paste(text: &str) {
    if text.is_empty() { return; }
    restore_overlay_focus();
    let active = active_window();
    let class = active.as_ref().and_then(|v| v["class"].as_str()).unwrap_or("unknown");
    let pid = active.as_ref().and_then(|v| v["pid"].as_u64()).unwrap_or(0);
    eprintln!("voicekey: sending {} characters to class {:?}, pid {}", text.chars().count(), class, pid);
    if !wtype(&["--", text]) { eprintln!("voicekey: direct text input failed"); }
}
pub fn caret() -> Option<Rect> { None }
pub fn secure_input() -> bool { false }
pub(crate) fn output_volume_default() -> Option<OutputVolumeSnapshot> { None }
pub(crate) fn output_volume_for(_: &OutputVolumeSnapshot) -> Option<OutputVolumeSnapshot> { None }
pub(crate) fn output_volume_write(_: &OutputVolumeSnapshot, _: &OutputVolumeSnapshot) -> Option<OutputVolumeSnapshot> { None }
pub mod perm {
    use super::*;
    pub fn accessibility(_: bool) -> bool { keyboards().iter().any(|p| File::open(p).is_ok()) }
    pub fn mic() -> MicStatus { MicStatus::Granted }
    pub fn request_mic() {}
    pub fn open_accessibility() {}
    pub fn open_mic() {}
}
pub mod keys {
    use crate::{HoldKey, Special, ALT, CTRL, META, SHIFT};
    pub fn modifier(code:u32)->Option<(u8,&'static str)> { Some(match code {42=>(SHIFT,"左 Shift"),54=>(SHIFT,"右 Shift"),29=>(CTRL,"左 Ctrl"),97=>(CTRL,"右 Ctrl"),56=>(ALT,"左 Alt"),100=>(ALT,"右 Alt"),125=>(META,"左 Win"),126=>(META,"右 Win"),_=>return None}) }
    pub fn special(code:u32)->Option<Special> { Some(match code {1=>Special::Escape,28=>Special::Enter,103=>Special::Up,108=>Special::Down,2..=10=>Special::Digit((code-1) as u8),_=>return None}) }
    pub fn is_function_key(code:u32)->bool { (59..=68).contains(&code) || (87..=88).contains(&code) || (183..=194).contains(&code) }
    pub fn special_name(code:u32)->Option<&'static str> { Some(match code {1=>"Esc",14=>"Backspace",15=>"Tab",28=>"Enter",57=>"Space",103=>"↑",108=>"↓",105=>"←",106=>"→",59=>"F1",60=>"F2",61=>"F3",62=>"F4",63=>"F5",64=>"F6",65=>"F7",66=>"F8",67=>"F9",68=>"F10",87=>"F11",88=>"F12",_=>return None}) }
    pub fn character(code:u32)->Option<&'static str> { Some(match code {2=>"1",3=>"2",4=>"3",5=>"4",6=>"5",7=>"6",8=>"7",9=>"8",10=>"9",11=>"0",16=>"Q",17=>"W",18=>"E",19=>"R",20=>"T",21=>"Y",22=>"U",23=>"I",24=>"O",25=>"P",30=>"A",31=>"S",32=>"D",33=>"F",34=>"G",35=>"H",36=>"J",37=>"K",38=>"L",44=>"Z",45=>"X",46=>"C",47=>"V",48=>"B",49=>"N",50=>"M",_=>return None}) }
    pub fn hold_keys()->&'static [HoldKey] { &[HoldKey{id:"rightAlt",code:100,name:"右 Alt"},HoldKey{id:"rightCtrl",code:97,name:"右 Ctrl"},HoldKey{id:"rightShift",code:54,name:"右 Shift"}] }
}
