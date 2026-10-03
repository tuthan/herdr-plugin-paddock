#!/usr/bin/env python3
"""paddock-relay: connect stdin/stdout to one herdr API socket (Python 3 standard library only).

    paddock-relay.py /home/you/.config/herdr/sessions/NAME/herdr.sock

Bytes are forwarded unchanged in both directions, so the newline-delimited JSON of the herdr API passes through
untouched. The script exits when the socket closes, or shortly after stdin reaches EOF. It never logs payloads:
the only thing it ever writes to stderr is a short reason code.
"""
import os, select, socket, stat, sys

DRAIN_SECONDS = 2.0   # after stdin EOF, keep delivering the socket's last bytes for this long
CHUNK = 65536


def fail(reason, code=2):
    sys.stderr.write("paddock-relay: %s\n" % reason)
    sys.exit(code)


def checked_path(argv):
    if len(argv) != 2:
        fail("usage: paddock-relay.py SOCKET")
    path = argv[1]
    if "\0" in path or not os.path.isabs(path) or os.path.basename(path) != "herdr.sock":
        fail("not a herdr socket path")
    real = os.path.realpath(path)
    if os.path.basename(real) != "herdr.sock":
        fail("path resolves outside a herdr socket")
    try:
        st = os.stat(real)
    except OSError:
        fail("socket not found", 3)
    if not stat.S_ISSOCK(st.st_mode) or st.st_uid != os.getuid():
        fail("not a socket of this user")
    return real


def main():
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.connect(checked_path(sys.argv))
    except OSError:
        fail("cannot connect", 3)
    stdin, stdout = sys.stdin.fileno(), sys.stdout.fileno()
    reading_stdin, deadline = True, None
    import time
    while True:
        wait = None if deadline is None else max(0.0, deadline - time.monotonic())
        if deadline is not None and wait == 0.0:
            return 0
        ready, _, _ = select.select([sock] + ([stdin] if reading_stdin else []), [], [], wait)
        if not ready and deadline is not None:
            return 0
        if sock in ready:
            data = sock.recv(CHUNK)
            if not data:
                return 0
            view = memoryview(data)
            while view:
                view = view[os.write(stdout, view):]
        if stdin in ready:
            data = os.read(stdin, CHUNK)
            if not data:
                reading_stdin = False
                try:
                    sock.shutdown(socket.SHUT_WR)
                except OSError:
                    return 0
                deadline = time.monotonic() + DRAIN_SECONDS
            else:
                try:
                    sock.sendall(data)
                except OSError:
                    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (BrokenPipeError, KeyboardInterrupt):
        sys.exit(0)
