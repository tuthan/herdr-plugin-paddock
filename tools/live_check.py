#!/usr/bin/env python3
"""A live run of both actions against a disposable herdr session, never the real configuration.

  tools/live_check.py --home /path/to/isolated-home --session paddock-test-plugin

The isolated home is a directory that is not your real home (use a short path under ~/.cache or /tmp: herdr's sockets live in
it). herdr is run with that HOME and no HERDR_* variables, so `plugin link`, the plugin's config and state, and the
`~/.ssh/authorized_keys` the plugin writes are all inside it. The session must already be running there and be named
paddock-test or paddock-test-<suffix>. Needs herdr 0.9.1 or newer, ssh-keygen and Python 3.8 or newer. Prints one PASS or FAIL
line per check and nothing that names this machine, its user or its host keys.

What it does: links this repository as the plugin `paddock`; seeds `<home>/.ssh/authorized_keys` with one foreign line that has no
trailing newline; with a terminal client attached, invokes `authorize-phone` (the popup), types a key line, and checks the file and
that the line was never drawn; invokes it again (already authorized); types a private-key header (refused, file unchanged); invokes
`show-pairing` (the popup). Then opens each pane entrypoint as a split pane, where the text can be read exactly, and checks the
pairing link field by field against the host's own key files.
"""
import argparse
import base64
import fcntl
import hashlib
import json
import os
import pty
import re
import select
import shutil
import signal
import stat
import struct
import subprocess
import sys
import termios
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
import paddock_plugin as pp  # noqa: E402

FAILED = []
TOTAL = [0]


def check(name, ok, detail=""):
    TOTAL[0] += 1
    print("%s  %s%s" % ("PASS" if ok else "FAIL", name, "" if ok or not detail else "  (" + detail + ")"))
    if not ok:
        FAILED.append(name)


class Client(object):
    """A herdr terminal client in a pty, so a popup has someone attached to type into it."""

    def __init__(self, env, session):
        self.pid, self.fd = pty.fork()
        if self.pid == 0:
            os.execvpe("herdr", ["herdr", "--session", session], env)
        fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 120, 0, 0))
        self.raw = b""
        self.pump(2.0)

    def pump(self, seconds):
        end = time.time() + seconds
        while time.time() < end:
            r, _, _ = select.select([self.fd], [], [], 0.1)
            if r:
                try:
                    data = os.read(self.fd, 65536)
                except OSError:
                    return
                if not data:
                    return
                self.raw += data

    def text(self):
        return re.sub(rb"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(\x07|\x1b\\)|\x1b[()][A-Z0-9]", b"", self.raw).decode("utf-8", "replace")

    def flat(self):
        """The screen text with all white space removed: the client draws runs of spaces as cursor moves, so words are not
        separated by spaces in the raw stream, and a needle has to be compared the same way."""
        return re.sub(r"\s+", "", self.text())

    def has(self, needle):
        return re.sub(r"\s+", "", needle) in self.flat()

    def wait_for(self, needle, seconds=8.0):
        end = time.time() + seconds
        while time.time() < end:
            if self.has(needle):
                return True
            self.pump(0.3)
        return self.has(needle)

    def type(self, s):
        os.write(self.fd, s.encode())
        self.pump(0.8)

    def clear(self):
        self.raw = b""

    def close(self):
        try:
            os.kill(self.pid, signal.SIGTERM)
            os.waitpid(self.pid, 0)
        except Exception:
            pass


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--home", required=True)
    ap.add_argument("--session", required=True)
    args = ap.parse_args()
    real_home = os.path.realpath(os.path.expanduser("~"))
    home = os.path.realpath(args.home)
    if not re.match(r"^paddock-test(-[a-z0-9]+)?$", args.session):
        sys.exit("refusing session %r: only paddock-test[-suffix] may be driven" % args.session)
    if home == real_home or not (home.startswith(real_home + "/.cache/") or home.startswith("/tmp/")):
        sys.exit("refusing --home %s: it must be an isolated directory under ~/.cache or /tmp, not your home" % home)
    env = {k: v for k, v in os.environ.items() if not k.startswith("HERDR_") and not k.startswith("XDG_")}
    env["HOME"] = home
    env["TERM"] = "xterm-256color"

    def herdr(*a, **kw):
        r = subprocess.run(["herdr", "--session", args.session] + list(a), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
        out = r.stdout.decode("utf-8", "replace")
        return r.returncode, (json.loads(out) if out.strip().startswith("{") else out)

    sessions = json.loads(subprocess.run(["herdr", "session", "list", "--json"], env=env, stdout=subprocess.PIPE).stdout)["sessions"]
    if not any(s["name"] == args.session and s["running"] for s in sessions):
        sys.exit("session %s is not running under that home" % args.session)

    ssh_dir = os.path.join(home, ".ssh")
    ak = os.path.join(ssh_dir, "authorized_keys")
    shutil.rmtree(ssh_dir, ignore_errors=True)
    os.mkdir(ssh_dir, 0o700)
    seed = b"ssh-ed25519 AAAAC3NzaC1lZDI1NTE5-synthetic-seed synthetic@example"  # deliberately no trailing newline
    with open(ak, "wb") as f:
        f.write(seed)
    os.chmod(ak, 0o644)  # looser than 600: the plugin tightens it

    tmp = os.path.join(home, "livekey")
    shutil.rmtree(tmp, ignore_errors=True)
    os.mkdir(tmp)
    subprocess.check_call(["ssh-keygen", "-q", "-t", "ecdsa", "-b", "256", "-N", "", "-C", "paddock@phone", "-f", os.path.join(tmp, "k")])
    with open(os.path.join(tmp, "k.pub")) as f:
        line = f.read().strip()
    key = pp.parse_key_line(line)
    body = line.split(" ")[1]

    rc, out = herdr("plugin", "link", ROOT)
    check("the plugin links with no warning", rc == 0 and out["result"]["type"] == "plugin_linked" and not out["result"]["plugin"].get("warnings"))
    rc, out = herdr("plugin", "action", "list", "--plugin", "paddock")
    ids = sorted(a["action_id"] for a in out["result"]["actions"]) if rc == 0 else []
    check("herdr lists the two actions", ids == ["authorize-phone", "show-pairing"], str(ids))
    if not herdr("pane", "list")[1]["result"]["panes"]:
        herdr("workspace", "create", "--cwd", "/tmp", "--label", args.session, "--no-focus")
    herdr_sock = [s for s in sessions if s["name"] == args.session][0]["socket_path"]

    def close_popup():
        import socket
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.connect(herdr_sock)
        s.sendall(b'{"id":"live","method":"popup.close","params":{}}\n')
        s.settimeout(3)
        try:
            s.recv(4096)
        except Exception:
            pass
        s.close()

    close_popup()
    client = Client(env, args.session)
    try:
        # ---- authorize-phone, as a popup ----------------------------------------------------------------------------------
        rc, out = herdr("plugin", "action", "invoke", "authorize-phone", "--plugin", "paddock")
        check("invoking authorize-phone starts the action", rc == 0 and out["result"]["type"] == "plugin_action_invoked")
        asked = client.wait_for("Key line:")
        check("the popup asks for the key line", asked)
        if not asked:
            raise RuntimeError("the popup did not appear; typing now would go to the herdr client's keys")
        client.clear()
        client.type(line + "\r")
        check("the popup reports the key as authorized", client.wait_for("Authorized this phone key"))
        check("the popup shows the key's fingerprint", client.has(key.fingerprint))
        check("the pasted line was never drawn", not client.has(body[:40]))
        with open(ak, "rb") as f:
            got = f.read()
        check("the file is the seed, a newline, then exactly the line", got == seed + b"\n" + line.encode() + b"\n")
        check("the foreign line is untouched byte for byte", got.startswith(seed))
        check("modes are 700 and 600", stat.S_IMODE(os.stat(ssh_dir).st_mode) == 0o700 and stat.S_IMODE(os.stat(ak).st_mode) == 0o600)
        client.type("\r")  # Enter closes the popup
        time.sleep(1.0)

        client.clear()
        herdr("plugin", "action", "invoke", "authorize-phone", "--plugin", "paddock")
        if not client.wait_for("Key line:"):
            raise RuntimeError("the second popup did not appear")
        check("a second run asks again", True)
        client.type(line + "\r")
        check("a second run says already authorized", client.wait_for("already authorized"))
        with open(ak, "rb") as f:
            check("the second run changed nothing", f.read() == got)
        client.type("\r")
        time.sleep(1.0)

        marker = "ZZLIVEMARKERZZ"
        client.clear()
        herdr("plugin", "action", "invoke", "authorize-phone", "--plugin", "paddock")
        if not client.wait_for("Key line:"):
            raise RuntimeError("the third popup did not appear")
        client.type("-----BEGIN OPENSSH PRIVATE KEY-----" + marker + "\r")
        check("a pasted private key is refused", client.wait_for("looks like a private key"))
        check("the private key text was never drawn", not client.has(marker) and not client.has("BEGIN OPENSSH"))
        with open(ak, "rb") as f:
            check("a refused paste changed nothing", f.read() == got)
        client.type("\r")
        time.sleep(1.0)

        # ---- show-pairing, as a popup -------------------------------------------------------------------------------------
        client.clear()
        rc, out = herdr("plugin", "action", "invoke", "show-pairing", "--plugin", "paddock")
        check("invoking show-pairing starts the action", rc == 0)
        if not client.wait_for("Host name or address the phone should use"):
            raise RuntimeError("the pairing popup did not appear")
        check("the popup asks which host the phone should use", True)
        client.type("\r")
        check("the popup shows a paddock://pair link", client.wait_for("paddock://pair?v=1&host="))
        client.type("\r")
        time.sleep(1.0)
    except RuntimeError as e:
        check("the popup phase ran", False, str(e))
    finally:
        client.close()
        close_popup()

    # ---- both entrypoints as split panes, where the text can be read exactly ---------------------------------------------------
    base = herdr("pane", "list")[1]["result"]["panes"][0]["pane_id"]

    def open_split(entry):
        rc, out = herdr("plugin", "pane", "open", "--plugin", "paddock", "--entrypoint", entry, "--placement", "split", "--no-focus")
        return out["result"]["plugin_pane"]["pane"]["pane_id"] if rc == 0 and "result" in out else None

    def read_text(pane):
        out = herdr("pane", "read", pane, "--source", "recent-unwrapped", "--lines", "80")[1]
        return out["result"]["read"]["text"] if isinstance(out, dict) and "result" in out else str(out)

    pane = open_split("show-pairing")
    check("show-pairing opens as a split pane", pane is not None)
    time.sleep(1.5)
    herdr("pane", "send-keys", pane, "enter")  # keep the default host
    time.sleep(1.0)
    text = read_text(pane)
    links = re.findall(r"paddock://pair\?\S+", text)
    check("the pane shows exactly one link", len(links) == 1, str(len(links)))
    if links:
        fields = dict(p.split("=", 1) for p in links[0][len("paddock://pair?"):].split("&"))
        want = [fp for _, _, fp in pp.read_host_key_fingerprints()]
        check("link: v=1 and the keys are v, host, port, user, fp[, session]", fields.get("v") == "1" and list(fields)[:5] == ["v", "host", "port", "user", "fp"], str(list(fields)))
        check("link: fp lists this host's key fingerprints in the contract order", fields.get("fp", "").split(",") == want)
        check("link: the fingerprints equal what ssh-keygen -lf prints", [x.split()[1] for x in subprocess.run(
            "for f in /etc/ssh/ssh_host_ed25519_key.pub /etc/ssh/ssh_host_ecdsa_key.pub /etc/ssh/ssh_host_rsa_key.pub; do [ -r $f ] && ssh-keygen -lf $f; done",
            shell=True, stdout=subprocess.PIPE).stdout.decode().splitlines()] == want)
        check("link: the port is sshd's", fields.get("port") == str(pp.sshd_port()))
        check("link: the user is the user running herdr", fields.get("user") == pp.current_user())
        check("link: the session is the one herdr named", fields.get("session") == args.session, "session field present: %s" % ("session" in fields))
        check("link: it holds no key line and no secret", "ecdsa-sha2" not in links[0] and body[:20] not in links[0] and "PRIVATE" not in links[0])
    check("the pane says the phone must be able to reach the host", "must be able to reach this name or address" in text)
    herdr("pane", "close", pane)

    pane = open_split("authorize-phone")
    check("authorize-phone opens as a split pane", pane is not None)
    time.sleep(1.5)
    herdr("pane", "send-text", pane, "ecdsa-sha2-nistp256 " + body + " a;touch$IFS/tmp/pdk-should-not-exist")
    herdr("pane", "send-keys", pane, "enter")
    time.sleep(1.0)
    check("a hostile comment is refused in a real pane", "comment may be up to 64" in read_text(pane))
    check("and nothing ran", not os.path.exists("/tmp/pdk-should-not-exist"))
    with open(ak, "rb") as f:
        check("and the file is unchanged", f.read() == got)
    herdr("pane", "close", pane)

    shutil.rmtree(tmp, ignore_errors=True)
    print("%d checks, %d failed" % (TOTAL[0], len(FAILED)))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
