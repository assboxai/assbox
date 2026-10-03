// SPDX-License-Identifier: GPL-3.0-or-later
use assbox_domain::{Error, Result};
use std::{
    path::PathBuf,
    process::{Command, Stdio},
};

#[derive(Debug, Default, Clone, Copy)]
pub struct Commands;
impl Commands {
    /// Nix embeds the exact tool closure at build time. Never trust the caller's PATH.
    pub fn path() -> &'static str {
        env!(
            "ASSBOX_TOOL_PATH",
            "Build in the Assbox Nix development shell; a trusted tool closure is required"
        )
    }
    pub fn executable(&self, name: &str) -> Result<PathBuf> {
        if name.is_empty()
            || name.starts_with('-')
            || !name
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || b"._+-".contains(&b))
        {
            return Err(Error::new("tool names cannot contain a path"));
        }
        for dir in Self::path().split(':') {
            let p = PathBuf::from(dir).join(name);
            if p.is_file() {
                return Ok(p);
            }
        }
        Err(Error::new(format!(
            "required tool is not in the trusted tool closure: {name}"
        )))
    }
    pub(crate) fn command(&self, name: &str, args: &[&str]) -> Result<Command> {
        let mut c = Command::new(self.executable(name)?);
        let effective_root = std::fs::read_to_string("/proc/self/status")
            .ok()
            .is_some_and(|text| {
                text.lines()
                    .find(|line| line.starts_with("Uid:"))
                    .and_then(|line| line.split_whitespace().nth(2))
                    == Some("0")
            });
        let home = if effective_root {
            "/root".to_owned()
        } else {
            std::env::var("HOME").unwrap_or_else(|_| "/var/empty".to_owned())
        };
        c.args(args)
            .env_clear()
            .env("PATH", Self::path())
            .env("HOME", home)
            .env("LC_ALL", "C.UTF-8")
            .env("NIX_CONFIG", "accept-flake-config = false\n");
        if name == "gh" {
            // Never import a human's login, extensions, pager or saved host config.
            c.env("GH_CONFIG_DIR", "/var/empty")
                .env("GH_HOST", "github.com")
                .env("GH_PROMPT_DISABLED", "1")
                .env("GH_NO_UPDATE_NOTIFIER", "1")
                .env("GH_NO_EXTENSION_UPDATE_NOTIFIER", "1")
                .env("GH_PAGER", "cat");
        }
        if let Some(ca) = option_env!("ASSBOX_CA_BUNDLE") {
            c.env("SSL_CERT_FILE", ca)
                .env("NIX_SSL_CERT_FILE", ca)
                .env("CURL_CA_BUNDLE", ca);
        }
        Ok(c)
    }
    pub fn capture(&self, name: &str, args: &[&str]) -> Result<Vec<u8>> {
        crate::command_output::capture(&mut self.command(name, args)?, name, None)
    }
    /// Count archive output in constant memory without writing a temporary file.
    pub fn output_size(&self, name: &str, args: &[&str]) -> Result<u64> {
        let mut child = self
            .command(name, args)?
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::inherit())
            .spawn()
            .map_err(|e| Error::new(e.to_string()))?;
        let counted = match child.stdout.take() {
            Some(mut stream) => std::io::copy(&mut stream, &mut std::io::sink()),
            None => {
                let _ = child.kill();
                let _ = child.wait();
                return Err(Error::new("missing archive stream"));
            }
        };
        if counted.is_err() {
            let _ = child.kill();
        }
        let status = child.wait().map_err(|e| Error::new(e.to_string()))?;
        let size = counted.map_err(|e| Error::new(e.to_string()))?;
        if !status.success() {
            return Err(Error::new(format!(
                "{name} archive sizing failed ({status})"
            )));
        }
        Ok(size)
    }
    pub fn text(&self, name: &str, args: &[&str]) -> Result<String> {
        String::from_utf8(self.capture(name, args)?)
            .map_err(|_| Error::new("tool output is not UTF-8"))
    }
    pub fn input(&self, name: &str, args: &[&str], input: &[u8]) -> Result<Vec<u8>> {
        crate::command_output::capture(&mut self.command(name, args)?, name, Some(input))
    }
    pub fn run(&self, name: &str, args: &[&str]) -> Result<()> {
        let status = self
            .command(name, args)?
            .stdin(Stdio::null())
            .status()
            .map_err(|e| Error::new(e.to_string()))?;
        if status.success() {
            Ok(())
        } else {
            Err(Error::new(format!("{name} failed ({status})")))
        }
    }
    pub fn succeeds(&self, name: &str, args: &[&str]) -> bool {
        self.run(name, args).is_ok()
    }
    /// Activation is permitted only for an already-built immutable system path.
    pub fn activate(&self, system: &str, action: &str) -> Result<()> {
        if !valid_store_system(system) || !matches!(action, "boot" | "switch") {
            return Err(Error::new("invalid system activation request"));
        }
        let status = Command::new(format!("{system}/bin/switch-to-configuration"))
            .arg(action)
            .env_clear()
            .env("PATH", Self::path())
            .env("HOME", "/root")
            .env("LC_ALL", "C.UTF-8")
            .stdin(Stdio::null())
            .status()
            .map_err(|e| Error::new(e.to_string()))?;
        if status.success() {
            Ok(())
        } else {
            Err(Error::new(format!(
                "activation failed ({status}); inspect the recovery journal"
            )))
        }
    }
    pub fn jq_fields(&self, json: &[u8], filter: &str) -> Result<Vec<String>> {
        let bytes = self.input("jq", &["-j", filter], json)?;
        if bytes.is_empty() {
            return Ok(Vec::new());
        }
        if bytes.last() != Some(&0) {
            return Err(Error::new("malformed structured tool output"));
        }
        bytes[..bytes.len() - 1]
            .split(|b| *b == 0)
            .map(|b| {
                String::from_utf8(b.to_vec()).map_err(|_| Error::new("non-UTF-8 structured field"))
            })
            .collect()
    }
}
pub use assbox_domain::source::valid_store_system;
