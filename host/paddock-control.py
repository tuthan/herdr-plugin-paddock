#!/usr/bin/env python3
"""paddock-control: run one `herdr terminal session control` with a lease (Python 3 standard library only).

    paddock-control.py LEASE_SECONDS HERDR SESSION PANE COLS ROWS [takeover]

stdin and stdout are herdr's control stream, passed through line by line: the phone writes JSON commands
(`terminal.input`, `terminal.resize`, `terminal.scroll`, `terminal.release`) and reads `terminal.frame` and
`terminal.closed` records. The one thing added is the lease. While the phone is connected it sends
`{"type":"paddock.lease"}` every few seconds (any command counts too); if LEASE_SECONDS pass with nothing from the
phone, the control session is released, so a phone that lost its link without closing it cannot keep the desktop out
of its terminal until the SSH server notices (which can take hours). A closed stdin releases it at once.

Only the arguments above are accepted and only herdr's own control command is run, with an argv built here. Lines from
the phone are forwarded only when they are JSON objects of the four command types; anything else is dropped. Nothing
the phone or the terminal sends is ever logged. This script's own stderr output is a short reason code; herdr's own
stderr (a refused connection, a rejected command) passes through unchanged.
"""
import json, os, re, select, signal, subprocess, sys, time

COMMANDS = {"terminal.input", "terminal.resize", "terminal.scroll", "terminal.mouse", "terminal.release"}
LEASE_TYPE = "paddock.lease"
RELEASE_LINE = b'{"type":"terminal.release"}\n'
SESSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")
PANE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_:.-]{0,63}\Z")
MAX_LINE = 1 << 20
CHUNK = 65536
MAX_BUFFER = 4 << 20   # queued output per direction; past it the script stops reading that side until it drains
GRACE_SECONDS = 3.0   # after a release, how long herdr gets to say goodbye before the process is killed


def fail(reason, code=2):
    sys.stderr.write("paddock-control: %s\n" % reason)
    sys.exit(code)


def parse(argv):
    if len(argv) not in (7, 8):
        fail("usage: paddock-control.py LEASE_SECONDS HERDR SESSION PANE COLS ROWS [takeover]")
    lease, herdr, session, pane, cols, rows = argv[1:7]
    takeover = False
    if len(argv) == 8:
        if argv[7] != "takeover":
            fail("unknown option")
        takeover = True
    try:
        lease, cols, rows = int(lease), int(cols), int(rows)
    except ValueError:
        fail("lease, cols and rows must be integers")
    if not 5 <= lease <= 120:
        fail("lease out of range")
    if not (1 <= cols <= 1000 and 1 <= rows <= 500):
        fail("geometry out of range")
    if not (os.path.isabs(herdr) and os.path.basename(herdr) == "herdr" and "\0" not in herdr and os.access(herdr, os.X_OK)):
        fail("not a herdr binary")
    if not SESSION.match(session):
        fail("invalid session name")
    if not PANE.match(pane):
        fail("invalid pane id")
    cmd = [herdr, "--session", session, "terminal", "session", "control", pane]
    if takeover:
        cmd.append("--takeover")
    cmd += ["--cols", str(cols), "--rows", str(rows)]
    return lease, cmd


def main():
    lease, cmd = parse(sys.argv)
    try:
        child = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, close_fds=True)
    except OSError:
        fail("cannot start herdr", 3)
    stdin, out, cin, cout = sys.stdin.fileno(), sys.stdout.fileno(), child.stdin.fileno(), child.stdout.fileno()
    for fd in (out, cin):
        os.set_blocking(fd, False)    # a stalled reader on either side must never stop the lease clock

    to_phone, to_child, pending = bytearray(), bytearray(), bytearray()
    stdin_open, child_stdin_open, child_out_open = True, True, True
    release_at = None          # monotonic time after which the child is killed; set by release()
    deadline = time.monotonic() + lease

    def release(reason):
        nonlocal release_at, child_stdin_open
        if release_at is not None:
            return
        sys.stderr.write("paddock-control: %s\n" % reason)
        sys.stderr.flush()
        if child_stdin_open:
            to_child.extend(RELEASE_LINE)
        release_at = time.monotonic() + GRACE_SECONDS

    def on_signal(signum, frame):
        release("signal")
    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGHUP, on_signal)
    signal.signal(signal.SIGINT, on_signal)

    def handle_line(line):
        nonlocal deadline
        try:
            obj = json.loads(line)
        except ValueError:
            return
        kind = obj.get("type") if isinstance(obj, dict) else None
        if not isinstance(kind, str):
            return
        if kind == LEASE_TYPE:
            deadline = time.monotonic() + lease
        elif kind in COMMANDS and len(to_child) < MAX_BUFFER:
            deadline = time.monotonic() + lease
            to_child.extend(line.rstrip(b"\r\n") + b"\n")

    flush_until = None         # once herdr is gone: how long the last output gets to reach the phone
    while True:
        now = time.monotonic()
        if release_at is None and now >= deadline:
            release("lease expired")
        if release_at is not None and now >= release_at:
            child.kill()
            break
        if not child_out_open and (not to_phone or (flush_until is not None and now >= flush_until)):
            break
        # A closed child stdin ends the child's input; do it once everything queued, the release included, is written.
        if release_at is not None and child_stdin_open and not to_child:
            try:
                child.stdin.close()
            except OSError:
                pass
            child_stdin_open = False
        wakes = [now + 1.0, deadline if release_at is None else release_at]
        if flush_until is not None:
            wakes.append(flush_until)
        reads = []
        if child_out_open and len(to_phone) < MAX_BUFFER:
            reads.append(cout)
        if stdin_open:
            reads.append(stdin)
        writes = ([out] if to_phone else []) + ([cin] if to_child and child_stdin_open else [])
        ready_r, ready_w, _ = select.select(reads, writes, [], max(0.0, min(wakes) - now))
        if cout in ready_r:
            data = os.read(cout, CHUNK)
            if not data:
                child_out_open = False
                flush_until = time.monotonic() + GRACE_SECONDS
            else:
                to_phone.extend(data)
        if stdin in ready_r:
            data = os.read(stdin, CHUNK)
            if not data:
                stdin_open = False
                release("stdin closed")
            else:
                pending.extend(data)
                while True:
                    nl = pending.find(b"\n")
                    if nl < 0:
                        break
                    line = bytes(pending[:nl])
                    del pending[:nl + 1]
                    if len(line) <= MAX_LINE:
                        handle_line(line)
                if len(pending) > 2 * MAX_LINE:
                    release("line too long")
                    pending.clear()
        if out in ready_w:
            try:
                sent = os.write(out, to_phone)
                del to_phone[:sent]
            except BlockingIOError:
                pass
            except OSError:
                to_phone.clear()
                release("stdout closed")
        if cin in ready_w:
            try:
                sent = os.write(cin, to_child)
                del to_child[:sent]
            except BlockingIOError:
                pass
            except OSError:
                to_child.clear()
                child_stdin_open = False
    try:
        return child.wait(timeout=GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        child.kill()
        return child.wait()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
