// SPDX-License-Identifier: GPL-3.0-or-later
#![forbid(unsafe_code)]
mod wizard;
mod user;

use assbox_domain::*;
use assbox_engine::manage;
use assbox_system::{commands::Commands,files,probe};
use std::{env,process::{Command,ExitCode}};

const HELP: &str = r#"Assbox — Assistant Box

  assbox install [--apply] [--release r-SEQUENCE]
      Interactive prepared-storage installer. --apply requires --release. Without --apply, display the plan only.
  assbox release verify TAG DIRECTORY   Authenticate/download without installing
  assbox status                         Show running, boot and maintenance state
  assbox doctor                         Check status and failed system units
  assbox check                          Validate and build without activation
  assbox rebuild [--boot]                Rebuild local NixOS configuration
  assbox update [--reboot]               Authenticate an immutable release and stage
  assbox cleanup                        Retain recovery generations and collect garbage
  assbox rollback                       Select a retained previous boot generation
  assbox recover [--rollback]            Inspect/recover an interrupted operation
  assbox package search NAME            Search this machine's pinned nixpkgs
  assbox package list                   List only CLI-managed additional packages
  assbox package add NAME                Build and activate one additional package
  assbox package remove NAME             Remove one CLI-managed additional package
  assbox config edit                    Edit human-owned /etc/nixos/local.nix
  assbox application set APP MODE [--accept-unfree]
                                        Stage one application and presentation;
                                        ChatGPT requires X11; consent permits unfree packages machine-wide
  assbox application setup               Onboard as the unprivileged agent user
  assbox logs                           Show the maintenance journal

Changes to machine configuration require sudo from the admin account.
Ordinary nixos-rebuild and /etc/nixos/local.nix remain fully supported.
"#;
fn edit() -> Result<()> {
    files::require_root()?;
    files::trusted_dir(std::path::Path::new("/etc/nixos"))?;
    files::regular(std::path::Path::new("/etc/nixos/local.nix"))?;
    let editor=env::var("EDITOR").unwrap_or_else(|_|"nano".to_owned());
    let mut words=editor.split_whitespace();
    let name=words.next().ok_or_else(||Error::new("EDITOR is empty"))?;
    let status=Command::new(user::installed_program(name)?).args(words).arg("/etc/nixos/local.nix")
        .env("PATH",Commands::path()).status().map_err(|e|Error::new(e.to_string()))?;
    if !status.success() { return Err(Error::new("editor failed")); }
    println!("Saved local configuration. Use sudo assbox check, then sudo assbox rebuild (or standard nixos-rebuild).");
    Ok(())
}
fn run(args: &[&str]) -> Result<()> {
    match args {
        []|["--help"]|["-h"]|["help"]=>{ print!("{HELP}"); Ok(()) },
        ["--version"]=>{ println!("assbox {} ({})",env!("CARGO_PKG_VERSION"),std::env::consts::ARCH); Ok(()) },
        ["install",rest @ ..]=>wizard::install(rest),
        ["status"]=>manage::status(),
        ["doctor"]=>{ manage::status()?; Commands.run("systemctl", &["--failed","--no-pager"])?; Ok(()) },
        ["check"]=>manage::check(),
        ["rebuild"]=>manage::rebuild(false),
        ["rebuild","--boot"]=>manage::rebuild(true),
        ["update"]=>manage::update(false),
        ["update","--reboot"]=>manage::update(true),
        ["cleanup"]=>manage::cleanup(),
        ["rollback"]=>manage::rollback(),
        ["recover"]=>manage::recover(false),
        ["recover","--rollback"]=>manage::recover(true),
        ["package","search",query]=>manage::search(query),
        ["package","list"]=>{ for name in manage::packages()? { println!("{}",name.as_str()); } Ok(()) },
        ["package","add",name]=>manage::package_change(PackageName::parse(name)?,true),
        ["package","remove",name]=>manage::package_change(PackageName::parse(name)?,false),
        ["config","edit"]=>edit(),
        ["application","set",app,presentation]=>manage::application_set(app.parse()?,presentation.parse()?,false),
        ["application","set",app,presentation,"--accept-unfree"]=>manage::application_set(app.parse()?,presentation.parse()?,true),
        ["application","setup"]=>user::setup(),
        ["logs"]=>Commands.run("journalctl", &["--unit=assbox-maintenance.service","--no-pager","-n","100"]),
        ["internal", "release-baseline", tag, directory]=>assbox_engine::inspect_release(tag,std::path::Path::new(directory),true),
        ["release", "verify", tag, directory]=>assbox_engine::inspect_release(tag,std::path::Path::new(directory),false),
        ["internal","maintenance"]=>manage::maintenance(false),
        ["internal","maintenance","--retry"]=>manage::maintenance(true),
        ["internal","boot-check"]=>manage::boot_check(),
        ["internal","hardware"]=>{ println!("{:#?}",probe::inventory(&Commands)?); Ok(()) },
        _=>Err(Error::new("unknown command or arguments; use assbox --help")),
    }
}
fn main() -> ExitCode {
    let args:Vec<String>=env::args().skip(1).collect();
    let borrowed:Vec<&str>=args.iter().map(String::as_str).collect();
    match run(&borrowed) {
        Ok(())=>ExitCode::SUCCESS,
        Err(e)=>{ eprintln!("assbox: {e}"); ExitCode::FAILURE },
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn unknown_arguments_do_not_start_operations() {
        for args in [vec!["nonsense"],vec!["update","--force-unverified"],vec!["install","--yes"],vec!["package","add","--impure"]] {
            assert!(run(&args).is_err());
        }
    }
    #[test]
    fn help_and_version_do_not_require_a_machine() {
        assert!(run(&["--help"]).is_ok());
        assert!(run(&["--version"]).is_ok());
    }
}
