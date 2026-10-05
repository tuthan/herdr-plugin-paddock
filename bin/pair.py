#!/usr/bin/env python3
"""pair: pair a phone from one popup. Shows the pairing link and its QR, takes the phone's public key line from whichever intake
answers first, shows its fingerprint, and writes ~/.ssh/authorized_keys only after an explicit approval.

Intakes, all optional and all said out loud: the LAN listener (the phone sends its key to the address and port in the link),
the camera (zbarcam reads the key's QR from the phone's screen; switched on only after you press Enter) and a pasted line (echo
off). The first complete line wins; it is checked exactly as authorize-phone checks a line, and nothing is written unless you
type `a` and Enter at the prompt: Reject is the default. In a herdr popup there are no arguments; for scripts and tests there are
(see --help). The rules are in the README, the listener's wire grammar is in PROTOCOL.md.
"""
import argparse
import os
import selectors
import shutil
import signal
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
import paddock_plugin as pp  # noqa: E402

LINGER_S = 6.0          # after a decision, how long a script run keeps answering a phone that has not yet been told
LISTENER_GRACE_S = 10.0  # the listener is closed this long after the window ends, whatever else the popup is doing


class Terminal(object):
    """Standard input as a non-blocking line source the selector can watch. It reads the file descriptor itself (never
    sys.stdin's buffer), so a line already read ahead is never lost between the key line and the answer to the prompt."""

    LIMIT = pp.MAX_INPUT_BYTES + 2

    def __init__(self, fd):
        self.fd = fd
        self.buf = b""
        self.eof = False
        self.polling = False  # a regular file or /dev/null cannot be watched; it is always ready, so it is just read
        self._skip = False    # inside the tail of a line that was too long
        self._sel = None

    def attach(self, sel):
        try:
            sel.register(self.fd, selectors.EVENT_READ, self.on_readable)
            self._sel = sel
        except (OSError, ValueError):
            self.polling = True

    def on_readable(self, fileobj=None, mask=None):
        if self.eof:
            return
        try:
            data = os.read(self.fd, 4096)
        except (BlockingIOError, InterruptedError):
            return
        except OSError:
            data = b""
        if not data:
            self.eof = True
            self.polling = False
            if self._sel is not None:  # an ended input stays readable for ever: stop watching it
                try:
                    self._sel.unregister(self.fd)
                except (KeyError, ValueError, OSError):
                    pass
                self._sel = None
            return
        if self._skip:
            end = data.find(b"\n")
            if end < 0:
                return
            data, self._skip = data[end + 1:], False
        self.buf += data

    def has_line(self):
        return self.eof or b"\n" in self.buf or len(self.buf) >= self.LIMIT

    def take_line(self):
        """One line as bytes with its terminator, or None. A line over the cap comes back cut at the cap (the key check refuses it
        for its length) and the rest of it is dropped; at the end of input a last line without a terminator counts."""
        end = self.buf.find(b"\n")
        if 0 <= end < self.LIMIT:
            line, self.buf = self.buf[:end + 1], self.buf[end + 1:]
            return line
        if len(self.buf) >= self.LIMIT:
            line = self.buf[:self.LIMIT]
            self.buf = self.buf[end + 1:] if end >= 0 else b""
            self._skip = end < 0
            return line
        if self.eof and self.buf:
            line, self.buf = self.buf, b""
            return line
        return None


class Reader(object):
    """The stream approve_prompt and pause read from: readline() keeps the popup's selector running (so the listener keeps
    answering the phone) until a line arrives, the input ends or [deadline] passes. Returns b"" for the last two."""

    def __init__(self, popup, deadline):
        self.popup = popup
        self.deadline = deadline
        self.timed_out = False

    @property
    def buffer(self):
        return self

    def readline(self, limit=-1):
        p = self.popup
        p.pump(p.term.has_line, self.deadline)
        line = p.term.take_line()
        if line is None:
            self.timed_out = not p.term.eof
            return b""
        return line


class Popup(object):
    def __init__(self, args, tty, out, err, clock=time.monotonic):
        self.args = args
        self.tty = tty
        self.out = out
        self.err = err
        self.clock = clock
        self.timeout = args.timeout
        self.deadline = clock() + self.timeout
        self.sel = selectors.DefaultSelector()
        self.term = Terminal(sys.stdin.fileno())
        self.echo = None
        self.listener = None
        self.sid = None
        self.camera = None          # a started CameraIntake, or None
        self.camera_ready = None    # the device the Enter key switches on, or None
        self.camera_started = False
        self.phase = "wait"
        self.candidate = None       # (where it came from, KeyLine)
        self.refusal = None         # (where it came from, Refusal) for the first complete line that failed the key check

    # -- output ----------------------------------------------------------------------------------------------------------------

    def say(self, text):
        self.out.write(text)
        self.out.flush()

    def problem(self, text):
        (self.out if self.tty else self.err).write(text)
        (self.out if self.tty else self.err).flush()

    # -- setup -----------------------------------------------------------------------------------------------------------------

    def link(self):
        """The pairing link and its fields, built the way show-pairing builds them, plus the listener's port and handle when listening."""
        a = self.args
        prints = pp.read_host_key_fingerprints(a.ssh_dir)
        if not prints:
            raise pp.Refusal("No readable SSH host key files were found in %s, so there is nothing for the phone to check. "
                             "A pairing link without a fingerprint is not made." % a.ssh_dir, 3)
        host = a.host or pp.default_host()
        if self.tty and not a.host:
            host = pp.prompt_host(host, sys.stdin, self.out)
        port = a.port if a.port is not None else pp.sshd_port()
        user = a.user or pp.current_user()
        session = pp.herdr_session(os.environ)
        if session is not None and not pp.SESSION_RE.match(session):
            session = None
        fps = [f for _, _, f in prints]
        pp.build_link(host, port, user, fps, session)  # the refusals first: a bad host, port or user stops before a socket is opened
        self.deadline = self.clock() + self.timeout    # the window starts when the link is made, not while the host name is typed
        self.start_listener()
        link = pp.build_link(host, port, user, fps, session, self.listener.port if self.listener else None, self.sid)
        return link, host, port, user, session

    def start_listener(self):
        """Opens the listener when it is wanted and possible; sets self.listener, or self.listener_note saying why not."""
        a = self.args
        self.listener_note = None
        if a.no_listen:
            self.listener_note = "listener: off (--no-listen)"
        elif a.stdin and not a.listen_ip:
            self.listener_note = "listener: off (a --stdin run opens it only when --listen-ip names the address)"
        else:
            ip = a.listen_ip or pp.lan_address()
            problem = pp.listen_address_problem(ip) if ip else None
            if not ip:
                self.listener_note = "listener: off (no LAN address was found for this machine's default route)"
            elif problem:
                self.listener_note = "listener: off (%s)" % problem
            else:
                sid = pp.new_sid()
                try:
                    self.listener = pp.PairListener(ip, sid, clock=self.clock, window_s=self.timeout, selector=self.sel)
                    self.sid = sid
                    self.deadline = self.listener.deadline
                except pp.Refusal as r:
                    self.listener_note = "listener: off (%s)" % r.message

    def camera_status(self):
        """What the camera intake can do: its device when it can run, else the reason it cannot."""
        a = self.args
        if a.no_camera:
            return None, "camera: off (--no-camera)"
        if not shutil.which("zbarcam"):
            return None, "camera: off (zbarcam is not installed; it comes with the zbar package)"
        device = pp.camera_device(a.camera_device)
        if device is None:
            return None, "camera: off (%s does not exist, so there is no camera to read)" % (a.camera_device or "/dev/video0")
        return device, None

    # -- the selector loop -----------------------------------------------------------------------------------------------------

    def pump(self, until, deadline):
        """Runs the intakes until until() is true (returns True) or [deadline] passes (False)."""
        while True:
            if self.term.polling:
                self.term.on_readable()
            self.poll_intakes()
            self.housekeeping()
            if until():
                return True
            now = self.clock()
            if now >= deadline:
                return False
            for key, mask in self.sel.select(min(deadline - now, 0.2)):
                key.data(key.fileobj, mask)
            if self.listener:
                self.listener.tick()

    def housekeeping(self):
        if self.listener and self.clock() >= self.deadline + LISTENER_GRACE_S:
            self.listener.close()
            self.listener = None

    def poll_intakes(self):
        """While waiting for the key: the first complete line from the listener, the camera or the terminal becomes the candidate
        (or the refusal). Anything that comes later is ignored here; the listener answers a second phone `busy` by itself."""
        if self.phase != "wait" or self.candidate or self.refusal:
            return
        if self.listener and self.listener.held is not None:
            src = self.listener.held_from
            self.candidate = ("the phone over the network" + (" (%s)" % src if src else ""), self.listener.held)
            return
        cam = self.camera
        if cam is not None and cam.finished:
            self.camera_off()
            if cam.text is not None:
                self.take(cam.text, "the camera")
                return
            self.say("Camera: %s, so no key was read. The other intakes are still waiting.\n" % cam.error)
        while self.candidate is None and self.refusal is None:
            line = self.term.take_line()
            if line is None:
                break
            if line in (b"\n", b"\r\n"):
                self.enter_pressed()
            else:
                self.take(line, "a pasted line")

    def take(self, data, where):
        try:
            key = pp.parse_key_line(data)
        except pp.Refusal as r:
            self.refusal = (where, r)
            return
        self.candidate = (where, key)
        if self.listener:
            self.listener.adopt(key)  # a phone that now sends a different key is told `busy`

    def enter_pressed(self):
        if self.tty and self.camera_ready and not self.camera_started:
            self.start_camera()

    def start_camera(self):
        self.camera_started = True
        cam = pp.CameraIntake(self.camera_ready)
        try:
            cam.start()
        except OSError as e:
            self.say("Camera: could not start zbarcam (%s). The other intakes are still waiting.\n" % (os.strerror(e.errno) if e.errno else "I/O error"))
            return
        self.camera = cam
        self.sel.register(cam.fileobj, selectors.EVENT_READ, cam.on_readable)
        self.say("Camera on: reading %s with zbarcam until a code is read or the time is up. Hold the phone's key QR in front of it.\n" % self.camera_ready)

    def camera_off(self):
        cam, self.camera = self.camera, None
        if cam is None:
            return
        try:
            self.sel.unregister(cam.fileobj)
        except (KeyError, ValueError, OSError):
            pass
        cam.stop()
        self.say("Camera off.\n")

    # -- the run ---------------------------------------------------------------------------------------------------------------

    def run(self):
        a = self.args
        self.term.attach(self.sel)
        try:
            link, host, port, user, session = self.link()
        except pp.Refusal as r:
            self.problem(("\n" if self.tty else "") + r.message + "\n")
            self.close_tty()
            return r.code
        self.say("Paddock: pair a phone\n\n"
                 "Open this link on the phone, or scan its QR code with Paddock. It holds no key and no secret: only public host-key\n"
                 "fingerprints%s.\n\n%s\n\n" % (", and the handle of this one pairing" if self.sid else "", link))
        self.say("  host %s (the phone must be able to reach this name or address; change it with --host)   port %d   user %s   session %s\n"
                 % (host, port, user, session or "(the default herdr session)"))
        if not a.no_qr:
            qr = pp.draw_qr(link)
            self.say("\n" + qr if qr is not None else "\nNo QR code is drawn (qrencode is not installed, or failed); open the link on the phone, or paste it into Add a machine.\n")
        self.camera_ready, camera_note = self.camera_status()
        if self.tty:
            self.echo = pp.EchoOff(sys.stdin)  # before the intakes are announced: from then on what is typed is not shown and not stale
        self.say("\nWaiting up to %d seconds for the phone's public key from whichever of these answers first:\n" % self.timeout)
        if self.listener:
            self.say("  listening on %s:%d for the phone (plain TCP, this network only, one key; the phone sends it from the app)\n" % self.listener.address)
            if host != self.listener.address[0]:
                self.say("    the phone connects to the link's host (%s) at that port, so that name must reach %s; if it does not, run again with --host %s\n"
                         % (host, self.listener.address[0], self.listener.address[0]))
        else:
            self.say("  %s\n" % self.listener_note)
        if self.camera_ready:
            if self.tty and not a.camera_now:
                self.say("  camera %s ready (turns on after you press Enter; it is not used before that)\n" % self.camera_ready)
            elif a.camera_now:
                self.say("  camera %s on now (--camera-now)\n" % self.camera_ready)
            else:
                self.say("  camera %s ready, but it stays off without a terminal unless --camera-now says otherwise\n" % self.camera_ready)
        else:
            self.say("  %s\n" % camera_note)
        self.say("  %s\n\n" % ("a pasted line: paste the key line here and press Enter (what you paste is not shown)" if self.tty
                               else "standard input (--stdin): the first line is the key line, the next one answers the approval prompt"))
        if a.camera_now and self.camera_ready:
            self.start_camera()

        def dead_end():  # nothing can arrive any more: input ended, no camera running, no listener
            return self.term.eof and self.camera is None and self.listener is None

        got = self.pump(lambda: self.candidate or self.refusal or dead_end(), self.deadline)
        self.camera_off()
        self.restore_terminal()
        if self.refusal:
            where, r = self.refusal
            self.problem("\nRefused (%s): %s\n" % (where, r.message))
            return self.finish(r.code)
        if not self.candidate:
            if got:
                self.problem("\nStandard input ended and no other intake is active, so nothing can arrive. Nothing was written.\n")
            else:
                self.problem("\nNo key arrived within %d seconds. Nothing was written.\n" % self.timeout)
            return self.finish(1)
        return self.finish(self.decide(*self.candidate))

    def restore_terminal(self):
        """Echo back on and typed-ahead input dropped, so only a deliberate answer reaches the prompt. A script's pipe keeps its lines."""
        if self.echo is not None:
            self.echo.restore()
            self.echo = None
            self.term.buf = b""

    def decide(self, where, key):
        """Shows the fingerprint, asks, and writes only on approval. Returns the exit code."""
        self.phase = "approve"
        self.say("\nA key arrived from %s. Not shown; only its fingerprint is.\n\n" % where)
        reader = Reader(self, self.deadline)
        approved = pp.approve_prompt(key.fingerprint, reader, self.out)
        self.say("\n")
        if approved:
            try:
                result = pp.authorize(self.args.home or os.path.expanduser("~"), key)
            except pp.Refusal as r:
                if self.listener:
                    self.listener.finish(None)  # nothing was written, so the phone must not be told ok
                self.problem("Approved, but not written: %s\n" % r.message)
                return r.code
            if self.listener:
                self.listener.finish(key)
            if result.status == "added":
                self.say("Authorized this phone key:\n  %s\nAdded one line to %s (mode 600). Nothing else in the file was changed.\n" % (result.fingerprint, result.path))
            else:
                self.say("This phone key is already authorized:\n  %s\n%s was not changed.\n" % (result.fingerprint, result.path))
            self.say("Now press Connect on the phone.\n")
            return 0
        if reader.timed_out:
            self.say("The time ran out before you answered. Nothing was written.\n")  # the listener says `expired` by itself
        else:
            if self.listener:
                self.listener.finish(None)
            self.say("Rejected. Nothing was written.\n")
        return 1

    def finish(self, code):
        """The way out of every path: a script run lets a waiting phone hear the result; a terminal run holds the popup open on Enter."""
        l = self.listener
        if l is not None and l.engaged and not self.tty:
            self.pump(lambda: l.told, self.clock() + LINGER_S)
        self.close_tty()
        return code

    def close_tty(self):
        if self.tty:
            self.phase = "done"
            pp.pause(Reader(self, float("inf")), self.out)

    def close(self):
        self.camera_off()
        if self.listener:
            self.listener.close()
        if self.echo is not None:
            self.echo.restore()
        self.sel.close()


def main(argv=None):
    ap = argparse.ArgumentParser(description="Pair a phone: show the pairing link and take the phone's public key from the listener, the camera or a paste, then approve its fingerprint.")
    ap.add_argument("--timeout", type=float, default=120.0, help="seconds to wait for the key, and to answer the prompt (default 120)")
    ap.add_argument("--no-qr", action="store_true", help="do not draw a QR code even when qrencode is installed")
    ap.add_argument("--no-camera", action="store_true", help="no camera intake")
    ap.add_argument("--camera-device", metavar="PATH", help="the video device for the camera intake (default /dev/video0)")
    ap.add_argument("--camera-now", action="store_true", help="switch the camera on at once instead of after Enter (for scripts and tests)")
    ap.add_argument("--no-listen", action="store_true", help="no LAN listener")
    ap.add_argument("--listen-ip", metavar="IP", help="listen on this IPv4 address instead of the default route's (a --stdin run listens only with this)")
    ap.add_argument("--stdin", action="store_true", help="for scripts and tests: the key line is the first line of standard input and the answer the next; no terminal")
    ap.add_argument("--ssh-dir", default="/etc/ssh", help="where the ssh_host_*_key.pub files are (default /etc/ssh)")
    ap.add_argument("--host", help="the name or address the phone connects to (default: this machine's hostname)")
    ap.add_argument("--port", type=int, help="the SSH port (default: sshd_config's first Port, else 22)")
    ap.add_argument("--user", help="the SSH user (default: the user running herdr)")
    ap.add_argument("--home", help="write this home directory's .ssh/authorized_keys instead of the current user's (for tests)")
    args = ap.parse_args(argv)
    if args.no_listen and args.listen_ip:
        ap.error("--no-listen and --listen-ip contradict each other")
    if not 1 <= args.timeout <= 3600:
        ap.error("--timeout must be 1 to 3600 seconds")
    tty = not args.stdin and sys.stdin.isatty()
    if not args.stdin and not tty:
        sys.stderr.write("There is no terminal to ask in. Run this from the herdr action, or pass --stdin to read the key line and the answer from standard input.\n")
        return 2
    popup = Popup(args, tty, sys.stdout, sys.stderr)

    def hangup(signum, frame):
        raise SystemExit(128 + signum)  # a closed popup still switches the camera off and closes the listener

    for name in ("SIGHUP", "SIGTERM"):
        try:
            signal.signal(getattr(signal, name), hangup)
        except (AttributeError, ValueError, OSError):
            pass
    try:
        return popup.run()
    except KeyboardInterrupt:
        sys.stderr.write("\nStopped. Nothing was written.\n")
        return 1
    except Exception as e:  # never a traceback: it could carry what was received
        sys.stderr.write("pair stopped on an internal error (%s). Nothing was written.\n" % e.__class__.__name__)
        return 70
    finally:
        popup.close()


if __name__ == "__main__":
    sys.exit(main())
