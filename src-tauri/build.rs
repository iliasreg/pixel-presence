use std::env;
use std::path::Path;

fn main() {
    // Cargo compiles an executable directly into this profile directory. Embed
    // it so the runtime can refuse autostart from disposable cargo output,
    // including a custom CARGO_TARGET_DIR.
    let out_dir = env::var_os("OUT_DIR").expect("Cargo sets OUT_DIR for build scripts");
    let profile_dir = Path::new(&out_dir)
        .ancestors()
        .nth(3)
        .expect("OUT_DIR has a cargo profile ancestor");
    println!(
        "cargo:rustc-env=PIXELPRESENCE_CARGO_PROFILE_DIR={}",
        profile_dir.display()
    );
    tauri_build::build()
}
