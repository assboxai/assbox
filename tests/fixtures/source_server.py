# SPDX-License-Identifier: GPL-3.0-or-later
"""An isolated VM's HTTPS archive mirror; every source still has its locked NAR."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import shutil
import ssl
import sys
from urllib.parse import urlsplit

mirror, certificate, key = map(Path, sys.argv[1:4])
releases = Path('/var/lib/assbox-acceptance')
routes = json.loads((mirror / 'routes.json').read_text())


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urlsplit(self.path).path
        if path == '/acceptance/build-token':
            if (releases / 'block-build-token').exists():
                self.send_error(503)
                return
            payload = b'assbox disposable build input\n'
            self.send_response(200)
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        if path in routes:
            source = mirror / routes[path]
        else:
            parts = path.split('/')
            if len(parts) != 7 or parts[1:5] != ['assboxai', 'assbox', 'releases', 'download'] or parts[5] not in ('r-1', 'r-2') or parts[6] != 'assbox-source.tar.gz':
                self.send_error(404)
                return
            source = releases / (parts[5] + '-assbox-source.tar.gz')
        if not source.is_file():
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header('Content-Type', 'application/gzip')
        self.send_header('Content-Length', str(source.stat().st_size))
        self.end_headers()
        with source.open('rb') as stream:
            shutil.copyfileobj(stream, self.wfile)


context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
context.load_cert_chain(certificate, key)
server = ThreadingHTTPServer(('0.0.0.0', 443), Handler)
server.socket = context.wrap_socket(server.socket, server_side=True)
server.serve_forever()
