// SPDX-License-Identifier: GPL-3.0-or-later
use assbox_domain::{Error, Result};
use assbox_system::{commands::Commands, files};
use std::{
    fs::{self, File, OpenOptions},
    io::{Read, Write},
    os::unix::{
        fs::{MetadataExt, OpenOptionsExt, PermissionsExt},
        process::CommandExt,
    },
    path::Path,
    process::Command,
};

const DIRECTORY: &str = "/home/agent/.config/assbox";
const PASSWORD_KEY: &str = "OPENCODE_SERVER_PASSWORD";
const MAX_CREDENTIAL_BYTES: u64 = 64 * 1024;

fn current_uid() -> Result<u32> {
    Commands
        .text("id", &["-u"])?
        .trim()
        .parse()
        .map_err(|_| Error::new("invalid user identity"))
}

fn invalid_credential() -> Error {
    Error::new(
        "OpenCode credential must be a private regular file owned by agent, containing only OPENCODE_SERVER_PASSWORD= followed by a nonempty unquoted password without whitespace, quotes or backslashes. Restore ~/.config/assbox/opencode.env, or remove it and rerun assbox component setup opencode-server to create a new password.",
    )
}

fn password(path: &Path, uid: u32) -> Result<String> {
    let meta = fs::symlink_metadata(path).map_err(|_| invalid_credential())?;
    if !meta.is_file() || meta.uid() != uid || meta.mode() & 0o077 != 0 {
        return Err(invalid_credential());
    }
    let mut record = String::new();
    File::open(path)
        .and_then(|file| {
            file.take(MAX_CREDENTIAL_BYTES + 1)
                .read_to_string(&mut record)
        })
        .map_err(|_| invalid_credential())?;
    if record.len() as u64 > MAX_CREDENTIAL_BYTES {
        return Err(invalid_credential());
    }
    let value = record
        .strip_suffix('\n')
        .unwrap_or(&record)
        .strip_prefix("OPENCODE_SERVER_PASSWORD=")
        .ok_or_else(invalid_credential)?;
    // This is Assbox's single-assignment format, not shell or EnvironmentFile
    // syntax. Pass these exact bytes to the child, without a second parser.
    if value.is_empty()
        || !value
            .bytes()
            .all(|b| b.is_ascii_graphic() && !b"\"'\\".contains(&b))
    {
        return Err(invalid_credential());
    }
    Ok(value.to_owned())
}

/// Publish complete durable bytes without ever replacing a concurrent winner.
/// A crash before publication can leave a private temporary file, not a partial
/// final credential; a crash afterward leaves the complete credential in place.
fn publish(path: &Path, write: impl FnOnce(&mut File) -> Result<()>) -> Result<()> {
    let parent = path.parent().ok_or_else(invalid_credential)?;
    let temporary = parent.join(format!(".opencode-{}", files::random_id()?));
    let mut file = files::io(
        OpenOptions::new()
            .write(true)
            .create_new(true)
            .mode(0o600)
            .open(&temporary),
    )?;
    let result = (|| {
        write(&mut file)?;
        files::io(file.sync_all())?;
        match fs::hard_link(&temporary, path) {
            Ok(()) => Ok(()),
            Err(e) if e.kind() == std::io::ErrorKind::AlreadyExists => Ok(()),
            Err(e) => Err(Error::new(e.to_string())),
        }
    })();
    let cleanup = files::io(fs::remove_file(&temporary));
    result?;
    cleanup?;
    files::io(files::io(File::open(parent))?.sync_all())
}

fn prepare_at(dir: &Path, uid: u32) -> Result<()> {
    files::io(fs::create_dir_all(dir))?;
    let meta = files::io(fs::symlink_metadata(dir))?;
    if !meta.is_dir() || meta.uid() != uid {
        return Err(invalid_credential());
    }
    files::io(fs::set_permissions(dir, fs::Permissions::from_mode(0o700)))?;
    let path = dir.join("opencode.env");
    match fs::symlink_metadata(&path) {
        Ok(_) => {}
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => {
            let secret: String = files::random_bytes::<32>()?
                .iter()
                .map(|b| format!("{b:02x}"))
                .collect();
            publish(&path, |file| {
                files::io(file.write_all(format!("{PASSWORD_KEY}={secret}\n").as_bytes()))
            })?;
        }
        Err(e) => return Err(Error::new(e.to_string())),
    }
    // Also validate an existing file or a concurrent setup's winning credential.
    password(&path, uid).map(|_| ())
}

pub fn prepare() -> Result<()> {
    prepare_at(Path::new(DIRECTORY), current_uid()?)
}

fn authenticated_command(path: &Path, uid: u32, program: &Path, args: &[&str]) -> Result<Command> {
    let password = password(path, uid)?;
    let mut command = Command::new(program);
    command.args(args).env(PASSWORD_KEY, password);
    Ok(command)
}

pub fn launch(mode: &str) -> Result<()> {
    let args: &[&str] = match mode {
        "serve" => &["serve", "--hostname", "127.0.0.1", "--port", "4096"],
        "attach" => &["attach", "http://127.0.0.1:4096"],
        _ => return Err(Error::new("unknown managed OpenCode mode")),
    };
    super::user::require_selected(assbox_domain::Component::OpencodeServer)?;
    let mut command = authenticated_command(
        &Path::new(DIRECTORY).join("opencode.env"),
        current_uid()?,
        &super::user::installed_program("opencode")?,
        args,
    )?;
    // Replace the wrapper so systemd/terminal child status and signals retain
    // their ordinary semantics. The password is never a command-line argument.
    Err(Error::new(command.exec().to_string()))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::{os::unix::fs::symlink, path::PathBuf};

    struct Fixture(PathBuf);
    impl Fixture {
        fn new() -> Self {
            let dir = std::env::temp_dir()
                .join(format!("assbox-opencode-{}", files::random_id().unwrap()));
            fs::create_dir(&dir).unwrap();
            fs::set_permissions(&dir, fs::Permissions::from_mode(0o700)).unwrap();
            Self(dir)
        }
        fn path(&self) -> PathBuf {
            self.0.join("opencode.env")
        }
        fn uid(&self) -> u32 {
            fs::metadata(&self.0).unwrap().uid()
        }
        fn write(&self, bytes: &[u8]) {
            fs::write(self.path(), bytes).unwrap();
            fs::set_permissions(self.path(), fs::Permissions::from_mode(0o600)).unwrap();
        }
    }
    impl Drop for Fixture {
        fn drop(&mut self) {
            fs::remove_dir_all(&self.0).unwrap();
        }
    }

    #[test]
    fn creation_is_private_and_reruns_preserve_the_password() {
        let fixture = Fixture::new();
        prepare_at(&fixture.0, fixture.uid()).unwrap();
        let value = password(&fixture.path(), fixture.uid()).unwrap();
        assert_eq!(value.len(), 64);
        assert!(value.bytes().all(|b| b.is_ascii_hexdigit()));
        assert_eq!(fs::metadata(fixture.path()).unwrap().mode() & 0o777, 0o600);
        assert_eq!(fs::metadata(&fixture.0).unwrap().mode() & 0o777, 0o700);
        let before = fs::read(fixture.path()).unwrap();
        prepare_at(&fixture.0, fixture.uid()).unwrap();
        assert_eq!(fs::read(fixture.path()).unwrap(), before);
        assert_eq!(fs::read_dir(&fixture.0).unwrap().count(), 1);
    }

    #[test]
    fn malformed_credentials_never_reach_a_child_or_get_rotated() {
        let fixture = Fixture::new();
        assert!(password(&fixture.path(), fixture.uid()).is_err());
        let mut invalid = vec![
            vec![],
            b"OPENCODE_SERVER_PASS".to_vec(),
            b"OPENCODE_SERVER_PASSWORD=\n".to_vec(),
            b"OPENCODE_SERVER_PASSWORD=\"\"\n".to_vec(),
            b"OPENCODE_SERVER_PASSWORD=''\n".to_vec(),
            b"OPENCODE_SERVER_PASSWORD=quoted\\\ncontinuation\n".to_vec(),
            b"OPENCODE_SERVER_PASSWORD=secret\nOPENCODE_SERVER_PASSWORD=\n".to_vec(),
            b"OPENCODE_SERVER_PASSWORD=secret\nOTHER=value\n".to_vec(),
            b"OPENCODE_SERVER_PASSWORD= secret\n".to_vec(),
            b"OPENCODE_SERVER_PASSWORD=secret \n".to_vec(),
            b"OPENCODE_SERVER_PASSWORD=secret\r\n".to_vec(),
            b"OPENCODE_SERVER_PASSWORD=sec\0ret\n".to_vec(),
            b"OPENCODE_SERVER_PASSWORD=\xff\n".to_vec(),
        ];
        invalid.push(
            format!(
                "{PASSWORD_KEY}={}\n",
                "x".repeat(MAX_CREDENTIAL_BYTES as usize)
            )
            .into_bytes(),
        );
        for record in invalid {
            fixture.write(&record);
            assert!(prepare_at(&fixture.0, fixture.uid()).is_err());
            assert!(
                authenticated_command(&fixture.path(), fixture.uid(), Path::new("/unused"), &[])
                    .is_err()
            );
            assert_eq!(fs::read(fixture.path()).unwrap(), record);
        }
    }

    #[test]
    fn metadata_failures_and_symlinks_are_rejected_without_changes() {
        let fixture = Fixture::new();
        fixture.write(b"OPENCODE_SERVER_PASSWORD=custom\n");
        assert!(password(&fixture.path(), fixture.uid() + 1).is_err());
        for mode in [0o640, 0o604, 0o666] {
            fs::set_permissions(fixture.path(), fs::Permissions::from_mode(mode)).unwrap();
            assert!(prepare_at(&fixture.0, fixture.uid()).is_err());
            assert_eq!(fs::metadata(fixture.path()).unwrap().mode() & 0o777, mode);
        }
        fs::remove_file(fixture.path()).unwrap();
        for target in ["missing", "existing"] {
            fs::write(
                fixture.0.join("existing"),
                b"OPENCODE_SERVER_PASSWORD=custom\n",
            )
            .unwrap();
            symlink(target, fixture.path()).unwrap();
            assert!(prepare_at(&fixture.0, fixture.uid()).is_err());
            assert!(fs::symlink_metadata(fixture.path()).unwrap().is_symlink());
            fs::remove_file(fixture.path()).unwrap();
        }
        fs::create_dir(fixture.path()).unwrap();
        assert!(prepare_at(&fixture.0, fixture.uid()).is_err());
    }

    #[test]
    fn write_failure_leaves_no_final_credential() {
        let fixture = Fixture::new();
        let result = publish(&fixture.path(), |file| {
            files::io(file.write_all(b"OPENCODE_SERVER_PASS"))?;
            assert!(!fixture.path().exists());
            Err(Error::new("injected write failure"))
        });
        assert!(result.is_err());
        assert!(!fixture.path().exists());
        assert_eq!(fs::read_dir(&fixture.0).unwrap().count(), 0);
        prepare_at(&fixture.0, fixture.uid()).unwrap();
    }

    #[test]
    fn interrupted_staging_is_never_published() {
        const CHILD_DIR: &str = "ASSBOX_TEST_INTERRUPTED_CREDENTIAL_DIR";
        if let Some(dir) = std::env::var_os(CHILD_DIR) {
            publish(&PathBuf::from(dir).join("opencode.env"), |file| {
                file.write_all(b"OPENCODE_SERVER_PASS").unwrap();
                // Exit without returning through publication or cleanup.
                std::process::exit(77);
            })
            .unwrap();
            unreachable!();
        }
        let fixture = Fixture::new();
        let status = Command::new(std::env::current_exe().unwrap())
            .args([
                "--exact",
                "opencode::tests::interrupted_staging_is_never_published",
            ])
            .env(CHILD_DIR, &fixture.0)
            .status()
            .unwrap();
        assert_eq!(status.code(), Some(77));
        assert!(!fixture.path().exists());
        let temporary = fs::read_dir(&fixture.0).unwrap().next().unwrap().unwrap();
        assert_eq!(temporary.metadata().unwrap().mode() & 0o777, 0o600);
        prepare_at(&fixture.0, fixture.uid()).unwrap();
        assert_eq!(password(&fixture.path(), fixture.uid()).unwrap().len(), 64);
    }

    #[test]
    fn concurrent_publication_preserves_the_winning_credential() {
        let fixture = Fixture::new();
        publish(&fixture.path(), |file| {
            files::io(file.write_all(b"OPENCODE_SERVER_PASSWORD=loser\n"))?;
            publish(&fixture.path(), |winner| {
                files::io(winner.write_all(b"OPENCODE_SERVER_PASSWORD=winner\n"))
            })
        })
        .unwrap();
        prepare_at(&fixture.0, fixture.uid()).unwrap();
        assert_eq!(password(&fixture.path(), fixture.uid()).unwrap(), "winner");
        assert_eq!(fs::read_dir(&fixture.0).unwrap().count(), 1);
    }

    #[test]
    fn custom_password_is_passed_literally_from_the_validated_snapshot() {
        let fixture = Fixture::new();
        for value in ["disposable-test-password", "literal$;#=()[]{}!+_-.:@%"] {
            for ending in ["", "\n"] {
                let record = format!("{PASSWORD_KEY}={value}{ending}");
                fixture.write(record.as_bytes());
                prepare_at(&fixture.0, fixture.uid()).unwrap();
                assert_eq!(fs::read(fixture.path()).unwrap(), record.as_bytes());
                let mut command = authenticated_command(
                    &fixture.path(),
                    fixture.uid(),
                    &Commands.executable("printenv").unwrap(),
                    &[PASSWORD_KEY],
                )
                .unwrap();
                assert_eq!(command.get_args().collect::<Vec<_>>(), [PASSWORD_KEY]);
                // A later edit must not alter the already validated child environment.
                fixture.write(b"OPENCODE_SERVER_PASSWORD=\n");
                let output = command.output().unwrap();
                assert!(output.status.success());
                assert_eq!(output.stdout, format!("{value}\n").as_bytes());
            }
        }
    }
}
