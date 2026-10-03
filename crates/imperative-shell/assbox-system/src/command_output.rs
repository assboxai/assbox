// SPDX-License-Identifier: GPL-3.0-or-later
//! Drain child pipes concurrently without retaining unbounded build diagnostics.
use assbox_domain::{Error, Result};
use std::{
    io::{self, Read, Write},
    process::{Command, Stdio},
    thread,
};

const STDOUT_LIMIT: usize = 32 * 1024 * 1024;
const STDERR_LIMIT: usize = 64 * 1024;

struct Captured {
    bytes: Vec<u8>,
    truncated: bool,
}

fn drain(mut reader: impl Read, limit: usize, tail: bool) -> io::Result<Captured> {
    let mut captured = Captured {
        bytes: Vec::new(),
        truncated: false,
    };
    let mut buffer = [0; 8192];
    loop {
        let count = match reader.read(&mut buffer) {
            Ok(0) => return Ok(captured),
            Ok(count) => count,
            Err(error) if error.kind() == io::ErrorKind::Interrupted => continue,
            Err(error) => return Err(error),
        };
        let room = limit - captured.bytes.len();
        captured.truncated |= count > room;
        if !tail {
            captured.bytes.extend_from_slice(&buffer[..count.min(room)]);
        } else if count >= limit {
            captured.bytes.clear();
            captured
                .bytes
                .extend_from_slice(&buffer[count - limit..count]);
        } else {
            if count > room {
                let discarded = count - room;
                captured.bytes.copy_within(discarded.., 0);
                captured.bytes.truncate(captured.bytes.len() - discarded);
            }
            captured.bytes.extend_from_slice(&buffer[..count]);
        }
        // Continue draining after the limit: closing a pipe or abandoning a
        // writer would change command behavior and could leave work running.
    }
}

pub(super) fn capture(command: &mut Command, name: &str, input: Option<&[u8]>) -> Result<Vec<u8>> {
    capture_with_limits(command, name, input, STDOUT_LIMIT, STDERR_LIMIT)
}

fn capture_with_limits(
    command: &mut Command,
    name: &str,
    input: Option<&[u8]>,
    stdout_limit: usize,
    stderr_limit: usize,
) -> Result<Vec<u8>> {
    let mut child = command
        .stdin(if input.is_some() {
            Stdio::piped()
        } else {
            Stdio::null()
        })
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|error| Error::new(format!("cannot execute {name}: {error}")))?;
    // These handles are guaranteed by the Stdio::piped configuration above.
    let stdout = child.stdout.take().expect("piped stdout");
    let stderr = child.stderr.take().expect("piped stderr");
    let stdin = child.stdin.take();
    let (status, output, errors, written) = thread::scope(|scope| {
        let output = scope.spawn(move || drain(stdout, stdout_limit, false));
        // The input interface also handles passwords. Drain but do not retain
        // or report that command's stderr, including on reader/write failures.
        let errors = scope
            .spawn(move || drain(stderr, if input.is_some() { 0 } else { stderr_limit }, true));
        let writer =
            input.map(|bytes| scope.spawn(move || stdin.expect("piped stdin").write_all(bytes)));
        let status = child.wait();
        if status.is_err() {
            let _ = child.kill();
            let _ = child.wait();
        }
        (
            status,
            output.join(),
            errors.join(),
            writer.map(|writer| writer.join()),
        )
    });
    let status = status.map_err(|error| Error::new(format!("cannot wait for {name}: {error}")))?;
    let output = output
        .map_err(|_| Error::new("stdout reader failed"))?
        .map_err(|error| Error::new(format!("cannot read {name} stdout: {error}")))?;
    let errors = errors
        .map_err(|_| Error::new("stderr reader failed"))?
        .map_err(|error| Error::new(format!("cannot read {name} stderr: {error}")))?;
    if !status.success() {
        if input.is_some() {
            return Err(Error::new(format!("{name} failed ({status})")));
        }
        let note = if errors.truncated {
            "[stderr truncated; showing final bytes]\n"
        } else {
            ""
        };
        return Err(Error::new(format!(
            "{name} failed ({status}): {note}{}",
            String::from_utf8_lossy(&errors.bytes)
        )));
    }
    if let Some(written) = written {
        written
            .map_err(|_| Error::new("stdin writer failed"))?
            .map_err(|error| Error::new(format!("cannot write {name} input: {error}")))?;
    }
    if output.truncated {
        return Err(Error::new("tool output exceeds the safety limit"));
    }
    Ok(output.bytes)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn helper(script: &str) -> Command {
        let mut command = Command::new("python3");
        // A broken pipe-draining regression must fail instead of hanging CI.
        command.args([
            "-c",
            &format!("import signal,sys; signal.alarm(10); {script}"),
        ]);
        command
    }

    #[test]
    fn noisy_success_and_failure_keep_only_bounded_output() {
        for exit in [0, 7] {
            let mut command = helper(&format!(
                "sys.stderr.buffer.write(b'BEGIN'+b'x'*262144+b'END'); sys.stdout.buffer.write(b'y'*262144); sys.exit({exit})"
            ));
            let tail_limit = 16384;
            let error =
                capture_with_limits(&mut command, "helper", None, 1024, tail_limit).unwrap_err();
            if exit == 0 {
                assert!(error.0.contains("output exceeds"));
            } else {
                assert!(error.0.contains("stderr truncated"));
                assert!(error.0.ends_with(&("x".repeat(tail_limit - 3) + "END")));
                assert!(!error.0.contains("BEGIN"));
                assert!(error.0.len() < tail_limit + 160);
            }
        }
    }

    #[test]
    fn verbose_stderr_does_not_fail_a_successful_command() {
        let mut command =
            helper("sys.stderr.buffer.write(b'x'*262144); sys.stdout.buffer.write(b'OK')");
        assert_eq!(
            capture_with_limits(&mut command, "helper", None, 32, 31).unwrap(),
            b"OK"
        );
    }

    #[test]
    fn both_output_pipes_are_drained_while_stdin_is_written() {
        let input = vec![b'i'; 262144];
        let mut command = helper(
            "sys.stderr.buffer.write(b'e'*131072); sys.stdout.buffer.write(b'o'*131072); sys.stdout.buffer.flush(); sys.stdout.buffer.write(sys.stdin.buffer.read())",
        );
        let output = capture_with_limits(&mut command, "helper", Some(&input), 524288, 31).unwrap();
        assert_eq!(&output[..131072], vec![b'o'; 131072]);
        assert_eq!(&output[131072..], input);
    }

    #[test]
    fn input_failures_do_not_disclose_secrets_in_stderr() {
        let mut command = helper("sys.stderr.buffer.write(sys.stdin.buffer.read()); sys.exit(7)");
        let error = capture_with_limits(&mut command, "helper", Some(b"SECRET_PASSWORD"), 32, 32)
            .unwrap_err();
        assert!(error.0.contains("failed"));
        assert!(!error.0.contains("SECRET_PASSWORD"));
    }

    #[test]
    fn exact_stdout_limit_is_accepted_but_an_extra_byte_is_not() {
        for count in [32, 33] {
            let mut command = helper(&format!("sys.stdout.buffer.write(b'x'*{count})"));
            let result = capture_with_limits(&mut command, "helper", None, 32, 32);
            if count == 32 {
                assert_eq!(result.unwrap(), vec![b'x'; 32]);
            } else {
                assert!(result.unwrap_err().0.contains("output exceeds"));
            }
        }
    }
}
