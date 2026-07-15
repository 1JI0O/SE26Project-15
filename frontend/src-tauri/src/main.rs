// Keeps the Windows GUI process out of the terminal Ctrl+C process group.
#![cfg_attr(target_os = "windows", windows_subsystem = "windows")]

fn main() {
    app_lib::run();
}
