// SPDX-License-Identifier: GPL-3.0-or-later
use assbox_domain::*;
use assbox_system::{commands::Commands,files,probe};
use std::{fs,io::Write,os::unix::fs::{MetadataExt,OpenOptionsExt,PermissionsExt},path::Path,process::Command};

fn interactive(program: &str,args: &[&str]) -> Result<()> {
    let uid=Commands.text("id", &["-u"])?;
    let uid=uid.trim().parse::<u32>().map_err(|_|Error::new("invalid user identity"))?;
    let runtime=format!("/run/user/{uid}");
    let status=Command::new(installed_program(program)?).args(args).env("PATH",format!("{}:/run/current-system/sw/bin",Commands::path()))
        .env("HOME","/home/agent").env("XDG_RUNTIME_DIR",&runtime).env("DBUS_SESSION_BUS_ADDRESS",format!("unix:path={runtime}/bus")).current_dir("/home/agent").status().map_err(|e|Error::new(e.to_string()))?;
    if status.success(){Ok(())}else{Err(Error::new(format!("{program} exited with {status}")))}
}
pub fn setup() -> Result<()> {
    if Commands.text("id", &["-un"])?.trim()!="agent" {
        return Err(Error::new("run onboarding as the unprivileged agent user: sudo -iu agent assbox application setup"));
    }
    let runtime=probe::runtime(&Commands)?;
    let application:Application=runtime.first().ok_or_else(||Error::new("application configuration missing"))?.parse()?;
    match application {
        Application::None=>{ println!("No application selected. The terminal and ordinary NixOS tools are ready."); Ok(()) },
        Application::Chatgpt=>{ println!("Sign in using the ChatGPT window in the X11 session. The Linux Remote workflow is supported; this profile is not headless."); Ok(()) },
        Application::Opencode=>{
            let dir=Path::new("/home/agent/.config/assbox");
            files::io(fs::create_dir_all(dir))?;
            files::io(fs::set_permissions(dir,fs::Permissions::from_mode(0o700)))?;
            let env=dir.join("opencode.env");
            if let Ok(meta)=fs::symlink_metadata(&env) {
                let uid=Commands.text("id", &["-u"])?;
                let uid=uid.trim().parse::<u32>().map_err(|_|Error::new("invalid user identity"))?;
                if !meta.is_file() || meta.uid()!=uid || meta.mode()&0o077!=0 {
                    return Err(Error::new("OpenCode credential file must be a private regular file owned by agent"));
                }
            } else {
                let secret: String=files::random_bytes::<32>()?.iter().map(|b|format!("{b:02x}")).collect();
                let mut file=files::io(fs::OpenOptions::new().write(true).create_new(true).mode(0o600).open(&env))?;
                files::io(file.write_all(format!("OPENCODE_SERVER_PASSWORD={secret}\n").as_bytes()))?;
                files::io(file.sync_all())?;
            }
            interactive("opencode", &["auth","login"])?;
            interactive("systemctl", &["--user","restart","assbox-opencode.service"])?;
            if runtime.get(1).is_some_and(|p| p != "headless") {
                interactive("systemctl", &["--user","restart","assbox-opencode-ui.service"])?;
            }
            println!("OpenCode server is configured on loopback. Its password stays in ~/.config/assbox/opencode.env.");
            Ok(())
        },
        Application::Openclaw=>{
            interactive("openclaw", &["onboard","--skip-daemon"])?;
            interactive("systemctl", &["--user","restart","assbox-openclaw.service"])?;
            if runtime.get(1).is_some_and(|p| p != "headless") {
                interactive("systemctl", &["--user","restart","assbox-openclaw-ui.service"])?;
            }
            println!("Assbox owns the user service. Codex and OpenCode are also installed; authenticate them separately when needed.");
            Ok(())
        },
    }
}


/// Only explicit editor/onboarding requests may resolve an installed UI program.
/// Storage, Nix and maintenance commands never use this fallback.
pub(crate) fn installed_program(name: &str) -> Result<std::path::PathBuf> {
    if name.is_empty() || name.starts_with('-') || !name.bytes().all(|b| b.is_ascii_alphanumeric() || b"._+-".contains(&b)) {
        return Err(Error::new("use an installed program basename, not a path or shell expression"));
    }
    if let Ok(path) = Commands.executable(name) { return Ok(path); }
    let path = files::io(fs::canonicalize(Path::new("/run/current-system/sw/bin").join(name)))?;
    if !path.starts_with("/nix/store") || !path.is_file() {
        return Err(Error::new("requested UI program is not an installed Nix executable"));
    }
    Ok(path)
}
