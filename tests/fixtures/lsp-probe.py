# SPDX-License-Identifier: GPL-3.0-or-later
"""Bounded by the VM's timeout: exercise a real language server over stdio."""
import json
import subprocess
import sys


def send(process, message):
    body = json.dumps({'jsonrpc': '2.0', **message}).encode()
    process.stdin.write(f'Content-Length: {len(body)}\r\n\r\n'.encode() + body)
    process.stdin.flush()


def response(process, request_id):
    while True:
        headers = {}
        while True:
            line = process.stdout.readline()
            if not line:
                raise RuntimeError('Language server closed stdout before its response')
            if line == b'\r\n':
                break
            key, value = line.decode().split(':', 1)
            headers[key.lower()] = value.strip()
        length = int(headers['content-length'])
        if not 0 < length <= 16 * 1024 * 1024:
            raise RuntimeError('Invalid language server frame length')
        body = process.stdout.read(length)
        if len(body) != length:
            raise RuntimeError('Truncated language server frame')
        message = json.loads(body)
        if message.get('id') == request_id:
            if 'error' in message:
                raise RuntimeError(message['error'])
            return message['result']
        if 'id' in message:
            raise RuntimeError('Unexpected server request: ' + str(message))


def main():
    process = subprocess.Popen([sys.argv[1]], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    try:
        send(process, {'id': 1, 'method': 'initialize', 'params': {
            'processId': None, 'rootUri': None, 'capabilities': {},
        }})
        result = response(process, 1)
        assert result['serverInfo']['name'] == 'rust-analyzer', result
        assert isinstance(result['capabilities'], dict) and result['capabilities'], result
        send(process, {'method': 'initialized', 'params': {}})
        send(process, {'id': 2, 'method': 'shutdown', 'params': None})
        assert response(process, 2) is None
        send(process, {'method': 'exit'})
        assert process.wait(timeout=10) == 0
    finally:
        if process.poll() is None:
            process.kill()
        process.wait()


if __name__ == '__main__':
    main()
