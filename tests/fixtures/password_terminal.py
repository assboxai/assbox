# SPDX-License-Identifier: GPL-3.0-or-later
"""Drive the real Rust password adapter and trusted systemd helper in a private TTY.

No password agent, system manager, root privileges or VM is involved. All input
is disposable. The ignored Rust child is reachable only in the test executable.
"""
import errno
import fcntl
import os
from pathlib import Path
import pty
import select
import signal
import sys
import termios
import time


def exercise(mode):
    master, slave = pty.openpty()
    original = termios.tcgetattr(slave)
    original[3] |= termios.ECHO | termios.ICANON | termios.ISIG
    termios.tcsetattr(slave, termios.TCSANOW, original)
    read_output, write_output = os.pipe()
    pid = os.fork()
    if pid == 0:
        try:
            os.setsid()
            fcntl.ioctl(slave, termios.TIOCSCTTY, 0)
            os.dup2(slave, 0)
            os.dup2(write_output, 1)
            os.dup2(slave, 2)
            for fd in (master, slave, read_output, write_output):
                if fd > 2:
                    os.close(fd)
            env = dict(os.environ, ASSBOX_PASSWORD_TEST_MODE=mode)
            os.execve(sys.argv[1], [sys.argv[1], "--ignored", "--exact",
                      "password_terminal_child", "--nocapture", "--test-threads=1"], env)
        finally:
            os._exit(127)
    os.close(write_output)
    streams = {master: bytearray(), read_output: bytearray()}
    helper = None
    status = None
    first_sent = second_sent = False
    deadline = time.monotonic() + 10
    try:
        while time.monotonic() < deadline:
            ready, _, _ = select.select(list(streams), [], [], 0.05)
            for fd in ready:
                try:
                    data = os.read(fd, 65536)
                except OSError as error:
                    if error.errno != errno.EIO:
                        raise
                    data = b""
                if data:
                    streams[fd].extend(data)
            terminal = streams[master]
            # systemd writes the prompt immediately before disabling echo.
            no_echo = not termios.tcgetattr(slave)[3] & termios.ECHO
            if not first_sent and b"Assbox password regression:" in terminal and no_echo:
                children = set()
                for path in Path(f"/proc/{pid}/task").glob("*/children"):
                    children.update(map(int, path.read_text().split()))
                assert len(children) == 1, (mode, children)
                helper = children.pop()
                assert os.getpgid(helper) == os.tcgetpgrp(master) == pid
                first_sent = True
                if mode.endswith(("-partial", "-line")):
                    # Freeze consumption to make the unread-input race deterministic.
                    os.kill(helper, signal.SIGSTOP)
                    stopped_by = time.monotonic() + 2
                    while "State:\tT" not in Path(f"/proc/{helper}/status").read_text():
                        assert time.monotonic() < stopped_by, "helper did not stop"
                        time.sleep(0.01)
                    queued = b"queued-disposable-password"
                    os.write(master, queued + (b"\n" if mode.endswith("-line") else b""))
                if mode == "success":
                    os.write(master, b"disposable-test-password\n")
                elif mode.startswith("interrupt"):
                    os.write(master, b"\x03")  # Real terminal-generated SIGINT.
                elif mode.startswith("helper-failure"):
                    os.kill(helper, signal.SIGKILL)
                else:
                    os.kill(pid, signal.SIGTERM if mode.startswith("terminate") else signal.SIGHUP)
            if (mode == "success" and not second_sent and no_echo
                    and b"Assbox second password:" in terminal):
                second_sent = True
                os.write(master, b"second-disposable-password\n")
            exited, current = os.waitpid(pid, os.WNOHANG)
            if exited:
                status = current
                break
        assert status is not None, (mode, "password prompt timed out", streams)
        for fd, output in streams.items():
            os.set_blocking(fd, False)
            while True:
                try:
                    data = os.read(fd, 65536)
                except BlockingIOError:
                    break
                if not data:
                    break
                output.extend(data)
        assert os.waitstatus_to_exitcode(status) == 0, (mode, streams)
        assert first_sent and (mode != "success" or second_sent), (mode, streams)
        restored = termios.tcgetattr(slave)
        # TCSETS2 may encode the input speed explicitly in c_cflag. Python's
        # separate ispeed/ospeed fields already compare the effective speeds.
        original[2] &= ~termios.CIBAUD
        restored[2] &= ~termios.CIBAUD
        assert restored == original, (mode, "terminal settings not restored", original, restored)
        assert not Path(f"/proc/{helper}").exists(), (mode, "password helper survived")
        # Read in noncanonical mode so a partial line cannot hide in the queue.
        readable = termios.tcgetattr(slave)
        readable[3] &= ~(termios.ICANON | termios.ECHO)
        readable[6][termios.VMIN] = 0
        readable[6][termios.VTIME] = 0
        termios.tcsetattr(slave, termios.TCSANOW, readable)
        os.set_blocking(slave, False)
        try:
            unread = os.read(slave, 4096)
        except BlockingIOError:
            unread = b""
        assert not unread, (mode, "password input survived cleanup")
        for output in streams.values():
            assert b"queued-disposable-password" not in output, (mode, "queued password leaked")
            assert b"disposable-test-password" not in output, (mode, "password leaked")
            assert b"second-disposable-password" not in output, (mode, "password leaked")
    finally:
        if status is None:
            # Also reap the helper on a regression that leaves the child blocked.
            try:
                os.killpg(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            os.waitpid(pid, 0)
        for fd in (master, slave, read_output):
            os.close(fd)
    print(f"password terminal: {mode} passed", flush=True)


cases = ["success", "terminate", "interrupt", "hangup", "helper-failure"]
cases += [mode + suffix for mode in ("terminate", "hangup", "helper-failure")
          for suffix in ("-partial", "-line")]
for case in cases:
    exercise(case)
