# SPDX-License-Identifier: GPL-3.0-or-later
"""Open a disposable login page through the real session URL handler."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import secrets
import subprocess
import threading
import time


def main():
    token = secrets.token_urlsafe(24)
    completed = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            if self.path != '/signin/' + token:
                self.send_error(404)
                return
            body = ("<!doctype html><title>Assbox browser callback</title>"
                    "<p>Disposable browser callback test</p><script>"
                    "fetch('/callback/" + token + "', {method: 'POST'});</script>").encode()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            # A fetched page alone is insufficient: its renderer must execute JS.
            if (self.path != '/callback/' + token
                    or self.headers.get('Origin') != origin
                    or 'Chrome/' not in self.headers.get('User-Agent', '')):
                self.send_error(400)
                return
            self.send_response(204)
            self.end_headers()
            completed.set()

    with ThreadingHTTPServer(('127.0.0.1', 0), Handler) as server:
        origin = 'http://127.0.0.1:' + str(server.server_port)
        server.timeout = 1
        opener = subprocess.Popen(['xdg-open', origin + '/signin/' + token])
        try:
            deadline = time.monotonic() + 60
            while not completed.is_set() and time.monotonic() < deadline:
                if opener.poll() not in [None, 0]:
                    raise RuntimeError('Session URL handler failed: ' + str(opener.returncode))
                server.handle_request()
            if not completed.is_set():
                raise RuntimeError('Browser did not render the page and complete its loopback callback')
        finally:
            if opener.poll() is None:
                opener.terminate()
                try:
                    opener.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    opener.kill()
            opener.wait()


if __name__ == '__main__':
    main()
