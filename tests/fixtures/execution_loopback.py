# SPDX-License-Identifier: GPL-3.0-or-later
"""Disposable real-socket witnesses; never included in the installed system."""

import argparse
import os
from pathlib import Path
import socket
import socketserver
import threading
import time


def serve(port):
    class TCP(socketserver.BaseRequestHandler):
        def handle(self):
            while data := self.request.recv(1024):
                self.request.sendall(str(os.getuid()).encode() + b":" + data)

    class UDP(socketserver.BaseRequestHandler):
        def handle(self):
            data, connection = self.request
            connection.sendto(
                str(os.getuid()).encode() + b":" + data, self.client_address
            )

    servers = []
    for family, address in ((socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")):
        for base, handler in (
            (socketserver.ThreadingTCPServer, TCP),
            (socketserver.ThreadingUDPServer, UDP),
        ):
            class Server(base):
                address_family = family
                allow_reuse_address = True
                daemon_threads = True

                def server_bind(self):
                    if family == socket.AF_INET6:
                        self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
                    super().server_bind()

            server = Server((address, port), handler)
            servers.append(server)
            threading.Thread(target=server.serve_forever, daemon=True).start()
    threading.Event().wait()


def connect(args):
    family = socket.AF_INET6 if ":" in args.address else socket.AF_INET
    kind = socket.SOCK_DGRAM if args.protocol == "udp" else socket.SOCK_STREAM
    connection = socket.socket(family, kind)
    connection.settimeout(2)
    if family == socket.AF_INET6:
        connection.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
    if args.source_port:
        connection.bind((args.address, args.source_port))
    connection.connect((args.address, args.port))
    return connection


def exchange(connection, uid):
    payload = b"disposable-loopback-witness"
    expected = str(uid).encode() + b":" + payload
    connection.sendall(payload)
    response = connection.recv(1024)
    while len(response) < len(expected):
        chunk = connection.recv(1024)
        if not chunk:
            break
        response += chunk
    assert response == expected, response


def probe(args):
    with connect(args) as connection:
        exchange(connection, args.uid)


def hold(args):
    state = Path(args.state)
    with connect(args) as connection:
        exchange(connection, args.uid)
        (state / "ready").write_text("connected\n")
        deadline = time.monotonic() + 60
        while not (state / "continue").exists():
            if time.monotonic() >= deadline:
                raise TimeoutError("Disposable controller did not revoke admission")
            time.sleep(0.05)
        try:
            exchange(connection, args.uid)
        except (OSError, AssertionError):
            result = "denied\n"
        else:
            result = "allowed\n"
        (state / "result").write_text(result)


def main():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    server = commands.add_parser("serve")
    server.add_argument("port", type=int)
    for name in ("probe", "hold"):
        client = commands.add_parser(name)
        client.add_argument("protocol", choices=("tcp", "udp"))
        client.add_argument("address", choices=("127.0.0.1", "::1"))
        client.add_argument("port", type=int)
        client.add_argument("uid", type=int)
        client.add_argument("--source-port", type=int, default=0)
        if name == "hold":
            client.add_argument("state")
    args = parser.parse_args()
    if args.command == "serve":
        serve(args.port)
    elif args.command == "hold":
        hold(args)
    else:
        probe(args)


if __name__ == "__main__":
    main()
