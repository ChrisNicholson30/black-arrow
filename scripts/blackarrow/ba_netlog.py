#!/usr/bin/env python3
"""Logging HTTP proxy used to observe what a program tries to reach.

Point a program at this proxy with HTTPS_PROXY / HTTP_PROXY and every outbound
request shows up as one JSON line: when it happened and which host it wanted.

By default each request is refused with a 503, so a benchmark run is offline,
repeatable, and sends nothing to third parties. With --tunnel, CONNECT requests
are relayed to the real host instead, for observing a live session.

The proxy sees only what honours the proxy environment. Anything that opens a
socket directly is invisible here and has to be caught another way (lsof).
"""

from __future__ import annotations

import argparse
import json
import select
import socket
import threading
import time


def _relay(client: socket.socket, upstream: socket.socket) -> None:
    sockets = [client, upstream]
    try:
        while True:
            readable, _, errored = select.select(sockets, [], sockets, 60)
            if errored or not readable:
                return
            for source in readable:
                data = source.recv(65536)
                if not data:
                    return
                (upstream if source is client else client).sendall(data)
    except OSError:
        return
    finally:
        upstream.close()


def _handle(client: socket.socket, log_path: str, lock: threading.Lock, tunnel: bool) -> None:
    try:
        client.settimeout(5)
        head = b""
        while b"\r\n\r\n" not in head and len(head) < 65536:
            chunk = client.recv(4096)
            if not chunk:
                break
            head += chunk
        request_line = head.split(b"\r\n", 1)[0].decode("latin-1", "replace")
        parts = request_line.split()
        method = parts[0] if parts else "?"
        target = parts[1] if len(parts) > 1 else "?"
        with lock, open(log_path, "a", encoding="utf-8") as log:
            log.write(json.dumps({"t_ns": time.time_ns(), "method": method, "target": target}) + "\n")

        if tunnel and method == "CONNECT" and ":" in target:
            host, _, port = target.rpartition(":")
            try:
                upstream = socket.create_connection((host, int(port)), timeout=10)
            except (OSError, ValueError):
                client.sendall(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n")
                return
            client.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            client.settimeout(None)
            _relay(client, upstream)
            return

        client.sendall(
            b"HTTP/1.1 503 Service Unavailable\r\n"
            b"Content-Length: 0\r\nConnection: close\r\n\r\n"
        )
    except OSError:
        pass
    finally:
        client.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--log", required=True, help="file to append one JSON line per request to")
    parser.add_argument("--port-file", required=True, help="file the chosen port is written to once listening")
    parser.add_argument("--tunnel", action="store_true", help="relay CONNECT requests instead of refusing them")
    args = parser.parse_args()

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", 0))
    server.listen(64)
    open(args.log, "a", encoding="utf-8").close()
    with open(args.port_file, "w", encoding="utf-8") as port_file:
        port_file.write(str(server.getsockname()[1]))

    lock = threading.Lock()
    while True:
        client, _ = server.accept()
        threading.Thread(target=_handle, args=(client, args.log, lock, args.tunnel), daemon=True).start()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
