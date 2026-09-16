// SPDX-License-Identifier: GPL-3.0-or-later
use assbox_domain::{Error, Result};
use std::{io::Write, path::PathBuf, process::{Command, Stdio}};

#[derive(Debug, Default, Clone, Copy)]
pub struct Commands;
impl Commands {
    /// Nix embeds the exact tool closure at build time. Never trust the caller's PATH.
    pub fn path() -> &'static str {
        env!("ASSBOX_TOOL_PATH", "Build in the Assbox Nix development shell; a trusted tool closure is required")
    }
    pub fn executable(&self, name: &str) -> Result<PathBuf> {
        if name.is_empty() || name.starts_with('-') || !name.bytes().all(|b| b.is_ascii_alphanumeric() || b"._+-".contains(&b)) { return Err(Error::new("tool names cannot contain a path")); }
        for dir in Self::path().split(':') {
            let p = PathBuf::from(dir).join(name);
            if p.is_file() { return Ok(p); }
        }
        Err(Error::new(format!("required tool is not in the trusted tool closure: {name}")))
    }
    fn command(&self, name: &str, args: &[&str]) -> Result<Command> {
        let mut c = Command::new(self.executable(name)?);
        let effective_root = std::fs::read_to_string("/proc/self/status").ok().is_some_and(|text|
            text.lines().find(|line|line.starts_with("Uid:")).and_then(|line|line.split_whitespace().nth(2)) == Some("0"));
        let home = if effective_root { "/root".to_owned() } else { std::env::var("HOME").unwrap_or_else(|_|"/var/empty".to_owned()) };
        c.args(args).env_clear().env("PATH", Self::path()).env("HOME", home)
            .env("LC_ALL", "C.UTF-8").env("NIX_CONFIG", "accept-flake-config = false\n");
        if name == "gh" {
            // Never import a human's login, extensions, pager or saved host config.
            c.env("GH_CONFIG_DIR", "/var/empty").env("GH_HOST", "github.com")
                .env("GH_PROMPT_DISABLED", "1").env("GH_NO_UPDATE_NOTIFIER", "1")
                .env("GH_NO_EXTENSION_UPDATE_NOTIFIER", "1").env("GH_PAGER", "cat");
        }
        if let Some(ca) = option_env!("ASSBOX_CA_BUNDLE") {
            c.env("SSL_CERT_FILE", ca).env("NIX_SSL_CERT_FILE", ca).env("CURL_CA_BUNDLE", ca);
        }
        Ok(c)
    }
    pub fn capture(&self, name: &str, args: &[&str]) -> Result<Vec<u8>> {
        let output = self.command(name,args)?.stdin(Stdio::null()).output()
            .map_err(|e| Error::new(format!("cannot execute {name}: {e}")))?;
        if !output.status.success() {
            return Err(Error::new(format!("{name} failed ({}): {}", output.status,
                String::from_utf8_lossy(&output.stderr))));
        }
        if output.stdout.len() > 32*1024*1024 { return Err(Error::new("tool output exceeds the safety limit")); }
        Ok(output.stdout)
    }
    pub fn text(&self, name: &str, args: &[&str]) -> Result<String> {
        String::from_utf8(self.capture(name,args)?).map_err(|_|Error::new("tool output is not UTF-8"))
    }
    pub fn input(&self, name: &str, args: &[&str], input: &[u8]) -> Result<Vec<u8>> {
        let mut child = self.command(name,args)?.stdin(Stdio::piped()).stdout(Stdio::piped())
            .stderr(Stdio::piped()).spawn().map_err(|e|Error::new(format!("cannot execute {name}: {e}")))?;
        // Inputs here are small (inventory JSON, password, or a hash manifest).
        let mut stdin = child.stdin.take().ok_or_else(||Error::new("child stdin unavailable"))?;
        let write = stdin.write_all(input);
        drop(stdin);
        let output = child.wait_with_output().map_err(|e|Error::new(e.to_string()))?;
        write.map_err(|e|Error::new(e.to_string()))?;
        if !output.status.success() {
            // Deliberately omit input and stderr: this interface also handles passwords.
            return Err(Error::new(format!("{name} failed ({})", output.status)));
        }
        Ok(output.stdout)
    }
    pub fn run(&self, name: &str, args: &[&str]) -> Result<()> {
        let status = self.command(name,args)?.stdin(Stdio::null()).status().map_err(|e|Error::new(e.to_string()))?;
        if status.success() { Ok(()) } else { Err(Error::new(format!("{name} failed ({status})"))) }
    }
    pub fn succeeds(&self, name: &str, args: &[&str]) -> bool { self.run(name,args).is_ok() }
    /// Activation is permitted only for an already-built immutable system path.
    pub fn activate(&self, system: &str, action: &str) -> Result<()> {
        if !valid_store_system(system) || !matches!(action,"boot"|"switch") {
            return Err(Error::new("invalid system activation request"));
        }
        let status=Command::new(format!("{system}/bin/switch-to-configuration"))
            .arg(action).env_clear().env("PATH",Self::path()).env("HOME","/root")
            .env("LC_ALL","C.UTF-8").stdin(Stdio::null()).status().map_err(|e|Error::new(e.to_string()))?;
        if status.success() { Ok(()) } else { Err(Error::new(format!("activation failed ({status}); inspect the recovery journal"))) }
    }
    pub fn jq_fields(&self, json: &[u8], filter: &str) -> Result<Vec<String>> {
        let bytes=self.input("jq", &["-j",filter],json)?;
        if bytes.is_empty() { return Ok(Vec::new()); }
        if bytes.last()!=Some(&0) { return Err(Error::new("malformed structured tool output")); }
        bytes[..bytes.len()-1].split(|b|*b==0).map(|b|
            String::from_utf8(b.to_vec()).map_err(|_|Error::new("non-UTF-8 structured field"))).collect()
    }
}
pub fn valid_store_system(s: &str) -> bool {
    let Some(name)=s.strip_prefix("/nix/store/") else { return false; };
    let Some((hash, rest))=name.split_once('-') else { return false; };
    hash.len()==32 && hash.bytes().all(|b|b"0123456789abcdfghijklmnpqrsvwxyz".contains(&b))
        && rest.starts_with("nixos-system-") && rest.bytes().all(|b| b.is_ascii_alphanumeric() || b"-._+".contains(&b))
}
