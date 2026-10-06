"""Shared code for the Paddock herdr plugin: the phone-key line check, the authorized_keys writer, the pairing link and the
pieces of the `pair` popup (camera read, approval prompt, LAN listener).

Python 3.8 or newer, standard library only. Nothing here runs a shell or reads anything but the files named below. The one
network socket is PairListener's, and only the `pair` popup opens it (LAN addresses only, one key, a short window; PROTOCOL.md
has the wire grammar). The rules (and the reason for each) are in the README; the numbers and the alphabets match the Paddock
app's own copy command and pairing-link parser, so a line one accepts the other accepts.
"""
import base64
import collections
import errno
import getpass
import glob
import hashlib
import hmac
import ipaddress
import json
import os
import re
import secrets
import selectors
import shutil
import socket
import stat
import subprocess
import sys
import time

KEY_TYPE = "ecdsa-sha2-nistp256"
CURVE = "nistp256"
MAX_INPUT_BYTES = 1024
COMMENT_RE = re.compile(r"^[A-Za-z0-9@._-]{1,64}\Z")
BASE64_RE = re.compile(r"^[A-Za-z0-9+/]+={0,2}\Z")
# The OpenSSH wire blob of a P-256 public key: string(type) string(curve) string(0x04 || X || Y).
_BLOB = (
    (19).to_bytes(4, "big") + KEY_TYPE.encode() + (8).to_bytes(4, "big") + CURVE.encode() + (65).to_bytes(4, "big") + b"\x04"
)
BLOB_LENGTH = len(_BLOB) + 64


class Refusal(Exception):
    """A reason to change nothing. The message is safe to show: it never repeats what the user typed."""

    def __init__(self, message, code=2):
        super().__init__(message)
        self.message = message
        self.code = code


def fingerprint(blob):
    """`SHA256:` and unpadded base64 of the blob, the form `ssh-keygen -l` prints."""
    return "SHA256:" + base64.b64encode(hashlib.sha256(blob).digest()).decode().rstrip("=")


class KeyLine(object):
    """One validated phone key line: `ecdsa-sha2-nistp256 <base64> [comment]`."""

    def __init__(self, line, blob, comment):
        self.line = line
        self.blob = blob
        self.comment = comment

    @property
    def fingerprint(self):
        return fingerprint(self.blob)


_PRIVATE_MARKERS = ("PRIVATE KEY", "BEGIN ", "-----BEGIN", "PUTTY-USER-KEY-FILE", "OPENSSH PRIVATE")


def looks_private(text):
    """True when the start of [text] reads as a private key (or a key container) rather than a public key line."""
    head = text[:4096].upper()
    return any(m in head for m in _PRIVATE_MARKERS)


def parse_key_line(data):
    """Validates [data] (bytes or str) as exactly one phone key line and returns a [KeyLine].

    One trailing line terminator is allowed (what Enter adds); nothing else. Raises [Refusal] with a message that never
    contains the input. A line that passes is never second-guessed: the private-key wording is only chosen for input that
    was refused anyway.
    """
    if isinstance(data, str):
        data = data.encode("utf-8", "surrogateescape")
    try:
        return _parse(data)
    except Refusal:
        if looks_private(data[:4096].decode("latin-1")):
            raise Refusal("That looks like a private key. Paddock never needs one: paste the phone's public key line, which starts with "
                          + KEY_TYPE + ". Nothing was written.")
        raise


def _parse(data):
    if len(data) > MAX_INPUT_BYTES:
        raise Refusal("That is too long to be a public key line (the limit is %d bytes). Nothing was written." % MAX_INPUT_BYTES)
    if data.endswith(b"\r\n"):
        data = data[:-2]
    elif data.endswith(b"\n"):
        data = data[:-1]
    if not data:
        raise Refusal("Nothing was pasted. Paste the one line the phone copied. Nothing was written.")
    for b in data:
        if b < 0x20 or b > 0x7E:
            if b in (0x0A, 0x0D):
                raise Refusal("That is more than one line. Paste exactly one key line. Nothing was written.")
            raise Refusal("That contains characters a key line never has (control or non-ASCII characters). Nothing was written.")
    text = data.decode("ascii")
    if text != text.strip(" "):
        raise Refusal("Remove the spaces before and after the key line. Nothing was written.")
    parts = text.split(" ")
    if parts[0] != KEY_TYPE and re.search(r"(^|[ ,])" + re.escape(KEY_TYPE) + r"( |$)", text):
        raise Refusal("Nothing may come before the key type: no options such as command= or from=. Nothing was written.")
    if len(parts) not in (2, 3) or any(p == "" for p in parts):
        raise Refusal("A key line is `" + KEY_TYPE + " <key> [comment]`, separated by single spaces. Nothing was written.")
    if parts[0] != KEY_TYPE:
        raise Refusal("Only " + KEY_TYPE + " keys are accepted (what the phone makes), with no options in front of the key type. Nothing was written.")
    if not BASE64_RE.match(parts[1]) or len(parts[1]) % 4 != 0:
        raise Refusal("The key part is not valid base64. Nothing was written.")
    try:
        blob = base64.b64decode(parts[1], validate=True)
    except Exception:
        raise Refusal("The key part is not valid base64. Nothing was written.")
    if base64.b64encode(blob).decode() != parts[1]:  # decoding drops the spare bits of the last character; OpenSSH and the app refuse that spelling
        raise Refusal("The key part is not valid base64. Nothing was written.")
    if len(blob) != BLOB_LENGTH or not blob.startswith(_BLOB):
        raise Refusal("The key part is not a P-256 public key. Nothing was written.")
    comment = parts[2] if len(parts) == 3 else None
    if comment is not None and not COMMENT_RE.match(comment):
        raise Refusal("The comment may be up to 64 letters, digits, @ . _ and -. Nothing was written.")
    return KeyLine(text, blob, comment)


# ---- authorized_keys ---------------------------------------------------------------------------------------------------------

class Result(object):
    def __init__(self, status, path, fp):
        self.status = status  # "added" or "already"
        self.path = path
        self.fingerprint = fp


def _lstat(path):
    try:
        return os.lstat(path)
    except OSError as e:
        if e.errno == errno.ENOENT:
            return None
        raise


def authorize(home, key):
    """Appends [key] to `<home>/.ssh/authorized_keys` unless that exact line is already there.

    Creates `.ssh` (700) and the file (600) when missing and sets those modes. Adds a newline first only when the file is
    not empty and does not end in one. Every other byte of the file is left as it was: the line is appended with O_APPEND
    in one write, never by rewriting the file. Refuses, changing nothing, when `.ssh` or the file is a symlink or not a plain
    directory or file, or when either is writable by group or others.
    """
    ssh_dir = os.path.join(home, ".ssh")
    path = os.path.join(ssh_dir, "authorized_keys")
    try:
        st = _lstat(ssh_dir)
        if st is not None:
            if stat.S_ISLNK(st.st_mode):
                raise Refusal(ssh_dir + " is a symbolic link, so it was not touched. Authorize the key by hand, or replace the link with a directory.", 3)
            if not stat.S_ISDIR(st.st_mode):
                raise Refusal(ssh_dir + " is not a directory, so it was not touched.", 3)
            if st.st_mode & 0o022:
                raise Refusal(ssh_dir + " is writable by group or others (mode %o). sshd would ignore keys in it; run chmod 700 on it, then try again." % (st.st_mode & 0o777), 3)
        fst = _lstat(path)
        if fst is not None:
            if stat.S_ISLNK(fst.st_mode):
                raise Refusal(path + " is a symbolic link, so it was not touched. Authorize the key by hand, or replace the link with a file.", 3)
            if not stat.S_ISREG(fst.st_mode):
                raise Refusal(path + " is not a regular file, so it was not touched.", 3)
            if fst.st_mode & 0o022:
                raise Refusal(path + " is writable by group or others (mode %o). sshd would ignore it; run chmod 600 on it, then try again." % (fst.st_mode & 0o777), 3)
        if st is None:
            os.mkdir(ssh_dir, 0o700)
        os.chmod(ssh_dir, 0o700)
        existing = b""
        if fst is not None:
            with open(path, "rb") as f:
                existing = f.read()
        wanted = key.line.encode("ascii")
        if any(line == wanted for line in existing.split(b"\n")):
            os.chmod(path, 0o600)
            return Result("already", path, key.fingerprint)
        prefix = b"\n" if existing and not existing.endswith(b"\n") else b""
        payload = prefix + wanted + b"\n"
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            view = memoryview(payload)
            while view:
                n = os.write(fd, view)
                view = view[n:]
            os.fsync(fd)
        finally:
            os.close(fd)
        os.chmod(path, 0o600)
        return Result("added", path, key.fingerprint)
    except Refusal:
        raise
    except OSError as e:
        raise Refusal("Could not update %s: %s. Nothing else was changed." % (path, os.strerror(e.errno) if e.errno else "I/O error"), 4)


# ---- pairing link ------------------------------------------------------------------------------------------------------------

HOST_RE = re.compile(r"^[A-Za-z0-9._:\[\]-]{1,253}\Z")
USER_RE = re.compile(r"^[A-Za-z0-9._-]{1,32}\Z")
SESSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")
SHA256_RE = re.compile(r"^SHA256:[A-Za-z0-9+/]{43}\Z")

# What the app can pin: display name, key type, and the order the fingerprints are listed in.
HOST_KEY_ORDER = (
    ("ED25519", "ssh-ed25519", "ssh_host_ed25519_key.pub"),
    ("ECDSA P-256", "ecdsa-sha2-nistp256", "ssh_host_ecdsa_key.pub"),
    ("ECDSA P-384", "ecdsa-sha2-nistp384", None),
    ("ECDSA P-521", "ecdsa-sha2-nistp521", None),
    ("RSA", "ssh-rsa", "ssh_host_rsa_key.pub"),
)
# If a host has more than four, RSA is kept over the two larger ECDSA curves: more clients can use it.
_KEEP_PRIORITY = ("ssh-ed25519", "ecdsa-sha2-nistp256", "ssh-rsa", "ecdsa-sha2-nistp384", "ecdsa-sha2-nistp521")
MAX_FINGERPRINTS = 4


def read_host_key_fingerprints(ssh_dir="/etc/ssh"):
    """[(display name, type, fingerprint)] for the host's own public key files, in display order, at most four.

    The fingerprint is computed from the .pub file's key blob, which is what `ssh-keygen -lf <file>` prints. A file that
    cannot be read, or whose key part does not match its own type name, is skipped.
    """
    found = {}
    for path in sorted(glob.glob(os.path.join(ssh_dir, "ssh_host_*_key.pub"))):
        try:
            with open(path, "r") as f:
                fields = f.read(8192).split()
            ktype, blob = fields[0], base64.b64decode(fields[1], validate=True)
        except Exception:
            continue
        if ktype not in [t for _, t, _ in HOST_KEY_ORDER]:
            continue
        # The blob starts with the type string; a file whose two disagree is not a key sshd would present.
        if not blob.startswith(len(ktype).to_bytes(4, "big") + ktype.encode()):
            continue
        found.setdefault(ktype, fingerprint(blob))
    keep = [t for t in _KEEP_PRIORITY if t in found][:MAX_FINGERPRINTS]
    return [(name, t, found[t]) for name, t, _ in HOST_KEY_ORDER if t in keep]


def sshd_port(config="/etc/ssh/sshd_config", conf_d="/etc/ssh/sshd_config.d", _depth=0):
    """The first uncommented `Port` sshd reads, following `Include`, else the first one in `sshd_config.d/*.conf`, else 22."""
    port = _first_port(config, os.path.dirname(config), _depth=0)
    if port is None and os.path.isdir(conf_d):
        for path in sorted(glob.glob(os.path.join(conf_d, "*.conf"))):
            port = _first_port(path, os.path.dirname(config), _depth=1)
            if port is not None:
                break
    return port if port is not None else 22


def _first_port(path, base, _depth):
    if _depth > 4:
        return None
    try:
        with open(path, "r") as f:
            lines = f.read(65536).splitlines()
    except (OSError, UnicodeDecodeError):
        return None
    for raw in lines:
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        words = line.replace("=", " ", 1).split()
        key = words[0].lower()
        if key == "match":
            return None  # Port is not allowed inside Match, and everything after it belongs to it
        if key == "port" and len(words) >= 2 and words[1].isdigit() and 1 <= int(words[1]) <= 65535:
            return int(words[1])
        if key == "include":
            for pattern in words[1:]:
                full = pattern if os.path.isabs(pattern) else os.path.join(base, pattern)
                for inc in sorted(glob.glob(full)):
                    found = _first_port(inc, base, _depth + 1)
                    if found is not None:
                        return found
    return None


def herdr_session(environ):
    """The named herdr session this plugin runs in, or None for the default session."""
    name = environ.get("HERDR_SESSION")
    if name:
        return name
    sock = environ.get("HERDR_SOCKET_PATH", "")
    m = re.search(r"/sessions/([^/]+)/herdr\.sock$", sock)
    return m.group(1) if m else None


def is_macos(platform=None):
    """True on macOS. [platform] is for the tests; it defaults to this interpreter's."""
    return (sys.platform if platform is None else platform) == "darwin"


def default_host(run=subprocess.run, platform=None):
    """What the phone is told to connect to when nobody says: this machine's LAN address (the default route's), because a phone almost never resolves
    the machine's host name (no mDNS, no shared DNS), and the host name only when there is no LAN address to give."""
    return lan_address(run, platform) or socket.gethostname()


def current_user():
    try:
        return getpass.getuser()
    except Exception:
        return ""


SID_RE = re.compile(r"^[A-Za-z0-9_-]{22}\Z")


def new_sid():
    """A fresh pairing session handle: 16 random bytes as 22 base64url characters. It names one popup run; it is not a key."""
    sid = secrets.token_urlsafe(16).rstrip("=")
    assert len(sid) == 22 and SID_RE.match(sid)
    return sid


def build_link(host, port, user, fingerprints, session=None, pair_port=None, sid=None):
    """`paddock://pair?v=1&host=…&port=…&user=…&fp=SHA256:…[,SHA256:…][&session=…][&pair=<port>&sid=<handle>]`.

    Refuses a field the app would refuse. The last two parameters are appended only when both [pair_port] (the listener's port)
    and [sid] are given, so the link without a listener is the one the first version made, byte for byte.
    """
    if not HOST_RE.match(host or ""):
        raise Refusal("The host may use letters, digits, . : - _ and [ ] (up to 253 characters).")
    if not isinstance(port, int) or not 1 <= port <= 65535:
        raise Refusal("The port must be 1 to 65535.")
    if not USER_RE.match(user or ""):
        raise Refusal("The user name may use letters, digits, . _ and - (up to 32 characters).")
    if not 1 <= len(fingerprints) <= MAX_FINGERPRINTS or not all(SHA256_RE.match(f) for f in fingerprints):
        raise Refusal("A pairing link needs one to four host-key fingerprints in SHA256: form.")
    if session is not None and not SESSION_RE.match(session):
        raise Refusal("The herdr session name is not one Paddock accepts.")
    if pair_port is not None and (not isinstance(pair_port, int) or isinstance(pair_port, bool) or not 1 <= pair_port <= 65535):
        raise Refusal("The pairing listener port must be 1 to 65535.")
    if sid is not None and not (isinstance(sid, str) and SID_RE.match(sid)):
        raise Refusal("The pairing handle must be 22 characters from A-Z, a-z, 0-9, _ and -.")
    link = "paddock://pair?v=1&host=%s&port=%d&user=%s&fp=%s" % (host, port, user, ",".join(fingerprints))
    if session is not None:
        link += "&session=" + session
    if pair_port is not None and sid is not None:
        link += "&pair=%d&sid=%s" % (pair_port, sid)
    return link


# ---- terminal helpers (the popup's side) ---------------------------------------------------------------------------------------

def read_line(prompt, hidden=False, stdin=None, stdout=None, limit=MAX_INPUT_BYTES + 2):
    """Prints [prompt] and returns one line of bytes (at most [limit], terminator included).

    With [hidden] and a terminal, echo is off while the line is typed or pasted, so a pasted private key is never drawn on
    the screen, and anything left over from a multi-line paste is discarded.
    """
    stdin = stdin or __import__("sys").stdin
    stdout = stdout or __import__("sys").stdout
    stdout.write(prompt)
    stdout.flush()
    fd = None
    old = None
    if hidden:
        try:
            import termios
            fd = stdin.fileno()
            old = termios.tcgetattr(fd)
            new = termios.tcgetattr(fd)
            new[3] &= ~termios.ECHO
            termios.tcsetattr(fd, termios.TCSADRAIN, new)
        except Exception:
            fd = None
    try:
        data = stdin.buffer.readline(limit)
    finally:
        if fd is not None:
            import termios
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
            try:
                termios.tcflush(fd, termios.TCIFLUSH)
            except Exception:
                pass
            stdout.write("\n")
            stdout.flush()
    return data


def pause(stdin=None, stdout=None):
    """Holds a popup open until Enter, so its text can be read before the popup closes with its command."""
    stdin = stdin or __import__("sys").stdin
    stdout = stdout or __import__("sys").stdout
    stdout.write("\nPress Enter to close. ")
    stdout.flush()
    try:
        stdin.buffer.readline(16)
    except Exception:
        pass


# ---- the pair popup: QR text, camera, approval, LAN address -----------------------------------------------------------------------

def draw_qr(link):
    """[link] as a terminal QR (`qrencode -t ANSIUTF8 -m 2`), or None when qrencode is not installed or fails. The light border is 2 modules: with 1
    a dark terminal comes right up against the code and a phone camera needs about a pixel more a module to find it."""
    qr = shutil.which("qrencode")
    if not qr:
        return None
    try:
        r = subprocess.run([qr, "-t", "ANSIUTF8", "-m", "2", link], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.decode("utf-8", "replace") if r.returncode == 0 else None


# The desktop clipboard tools in the order they are tried, each with the variable that says the session has that display server.
CLIPBOARD_TOOLS = (("wl-copy", ["wl-copy"], "WAYLAND_DISPLAY"), ("xclip", ["xclip", "-selection", "clipboard"], "DISPLAY"),
                   ("xsel", ["xsel", "--clipboard", "--input"], "DISPLAY"))


# macOS has one clipboard and no display variable. xclip or xsel there would write XQuartz's clipboard, not the one Cmd+V reads, so they are not tried.
MACOS_CLIPBOARD_TOOLS = (("pbcopy", ["pbcopy"], None),)


def clipboard_tools(platform=None):
    return MACOS_CLIPBOARD_TOOLS if is_macos(platform) else CLIPBOARD_TOOLS


def clipboard_tool_names(platform=None):
    """The clipboard tools the popup tries on this platform, for the messages that name them."""
    return ", ".join(name for name, _, _ in clipboard_tools(platform))


def copy_to_clipboard(text, env=None, run=subprocess.run, platform=None):
    """Puts [text] on the desktop clipboard with pbcopy (macOS), wl-copy (Wayland), xclip or xsel (X11), the first the session can use. Returns the tool's
    name, or None when none is installed or none worked. Nothing but [text] is given to it, and what it prints is dropped."""
    env = os.environ if env is None else env
    for name, cmd, display in clipboard_tools(platform):
        path = shutil.which(name)
        if not path or (display and not env.get(display)):
            continue
        try:
            r = run([path] + cmd[1:], input=text.encode("utf-8"), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
        except (OSError, subprocess.SubprocessError):
            continue
        if r.returncode == 0:
            return name
    return None


def osc52_copy(text):
    """The terminal escape that asks the terminal itself to put [text] on the clipboard (OSC 52). Not every terminal, and no multiplexer, passes it on."""
    return "\033]52;c;%s\a" % base64.b64encode(text.encode("utf-8")).decode("ascii")


def prompt_host(default, stdin, stdout):
    """The question show-pairing and pair ask: which name or address the phone should use. Enter keeps [default]; three tries."""
    for _ in range(3):
        typed = read_line("Host name or address the phone should use [%s]: " % default, stdin=stdin, stdout=stdout).decode("utf-8", "replace").strip()
        if not typed:
            break
        if HOST_RE.match(typed):
            return typed
        stdout.write("That is not a host name or address.\n")
    return default


def camera_device(explicit=None):
    """The V4L2 device to read: [explicit] when given and present, else /dev/video0 when present, else None.

    A named device that is missing is not replaced by another one: the user asked for that camera, so a different one is
    never switched on in its place.
    """
    if explicit:
        return explicit if os.path.exists(explicit) else None
    return "/dev/video0" if os.path.exists("/dev/video0") else None


def camera_blocker(platform=None):
    """Why the camera intake cannot exist on this platform, or None. It reads a V4L2 device through zbarcam, and macOS has neither."""
    if is_macos(platform):
        return "camera: off (the camera intake needs a V4L2 camera and zbarcam, which macOS does not have; paste the key line or use the listener)"
    return None


ZBARCAM_ARGS = ("--raw", "--oneshot", "--nodisplay", "--prescale=640x480")


def camera_command(device):
    return ["zbarcam"] + list(ZBARCAM_ARGS) + [device]


def qr_text(raw):
    """What a zbarcam run printed, as text: at most MAX_INPUT_BYTES + 2 bytes, one trailing line break removed. None when empty.

    Nothing else is trimmed: a code that holds two lines stays two lines, and parse_key_line refuses it.
    """
    raw = raw[:MAX_INPUT_BYTES + 2]
    if raw.endswith(b"\r\n"):
        raw = raw[:-2]
    elif raw.endswith(b"\n"):
        raw = raw[:-1]
    return raw.decode("utf-8", "surrogateescape") if raw else None


def read_qr(device, timeout_s, run=subprocess.run):
    """Blocks up to [timeout_s] on `zbarcam --raw --oneshot --nodisplay --prescale=640x480 <device>`; the decoded text or None.

    None for a timeout, a non-zero exit, no zbarcam on PATH, or nothing printed; it never raises for those. (The popup uses
    CameraIntake instead, so the camera can be switched off the moment another intake answers.)
    """
    try:
        r = run(camera_command(device), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=timeout_s)
    except (OSError, subprocess.SubprocessError):
        return None
    out = r.stdout.encode() if isinstance(r.stdout, str) else r.stdout
    if r.returncode != 0 or not out:
        return None
    return qr_text(out)


class CameraIntake(object):
    """zbarcam run by the popup, read through a pipe the popup's selector watches, so it can be killed at any moment.

    Call start() only after the user has asked for the camera. The text is complete when zbarcam exits (--oneshot exits after one
    code), so a code that holds a second line is never cut down to its first one. [text] is set on success, [error] says why
    there is none (never what the camera saw).
    """

    def __init__(self, device, popen=subprocess.Popen):
        self.device = device
        self._popen = popen
        self.proc = None
        self.buf = b""
        self.finished = False
        self.text = None
        self.error = None

    @property
    def fileobj(self):
        return self.proc.stdout

    def start(self):
        self.proc = self._popen(camera_command(self.device), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        os.set_blocking(self.proc.stdout.fileno(), False)

    def on_readable(self, fileobj=None, mask=None):
        if self.finished:
            return
        try:
            chunk = os.read(self.proc.stdout.fileno(), 4096)
        except (BlockingIOError, InterruptedError):
            return
        except OSError:
            chunk = b""
        if chunk:
            self.buf += chunk
            if len(self.buf) > MAX_INPUT_BYTES + 2:  # far past any key line: stop reading, the size check refuses it
                self.stop()
                self._finish(0)
            return
        try:
            code = self.proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self.stop()
            code = -9
        self._finish(code)

    def _finish(self, code):
        self.finished = True
        self.text = qr_text(self.buf) if code == 0 else None
        if self.text is None:
            self.error = ("zbarcam exited with status %d" % code) if code != 0 else "no code was read"

    def stop(self):
        """Kills zbarcam if it is still running and closes the pipe. Safe to call twice, or before start()."""
        if self.proc is None:
            return
        if self.proc.poll() is None:
            try:
                self.proc.kill()
                self.proc.wait(timeout=2)
            except (OSError, subprocess.SubprocessError):
                pass
        try:
            self.proc.stdout.close()
        except OSError:
            pass


def fingerprint_head(fp):
    """The first eight characters after `SHA256:`: the part the owner compares first."""
    return fp[7:15] if fp.startswith("SHA256:") else fp[:8]


def approve_prompt(fingerprint, stdin, stdout):
    """Shows [fingerprint] and asks whether to approve. True only for `a` or `A` followed by Enter.

    Plain ASCII, so it reads the same without colour. Reject is the default and is listed first: an empty line, any other
    answer, a line without its Enter, or the end of input all mean Reject. [stdin] may be a text or a binary stream.
    """
    stdout.write("Phone key fingerprint:\n  %s\n  first 8 characters:  [%s]\n\n" % (fingerprint, fingerprint_head(fingerprint)))
    stdout.write("Approve only if the phone shows the same fingerprint.\n")
    stdout.write("[R]eject (default) / [a]pprove, then Enter: ")
    stdout.flush()
    try:
        answer = getattr(stdin, "buffer", stdin).readline(64)
    except (OSError, ValueError):
        answer = b""
    if isinstance(answer, bytes):
        answer = answer.decode("latin-1")
    for end in ("\r\n", "\n"):
        if answer.endswith(end):
            return answer[:-len(end)] in ("a", "A")
    return False


_IFACE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,14}\Z")


def _ip_json(run, args):
    try:
        r = run(["ip", "-json", "-4"] + args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    try:
        data = json.loads(r.stdout)
    except ValueError:
        return None
    return data if isinstance(data, list) else None


def _run_text(run, cmd):
    """The stdout of [cmd] as text, or None when it cannot run, times out or fails."""
    try:
        r = run(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.decode("utf-8", "replace") if r.returncode == 0 else None


def _macos_lan_address(run):
    """macOS has no `ip`: the default route's interface from `route -n get default`, its address from `ipconfig getifaddr <interface>`."""
    m = re.search(r"^\s*interface:\s*(\S+)\s*$", _run_text(run, ["route", "-n", "get", "default"]) or "", re.M)
    if not m or not _IFACE_RE.match(m.group(1)):
        return None
    try:
        ip = ipaddress.IPv4Address((_run_text(run, ["ipconfig", "getifaddr", m.group(1)]) or "").strip())
    except ValueError:
        return None
    return None if ip.is_unspecified else str(ip)


def _macos_lan_network(ip_text, run):
    """The network [ip_text] is on, from `ifconfig` (`inet 192.168.1.5 netmask 0xffffff00 ...`: the mask is hexadecimal and must be contiguous)."""
    for m in re.finditer(r"^\s*inet (\d{1,3}(?:\.\d{1,3}){3}) netmask 0x([0-9a-fA-F]{8})\b", _run_text(run, ["ifconfig"]) or "", re.M):
        if m.group(1) != ip_text:
            continue
        mask = int(m.group(2), 16)
        inverse = ~mask & 0xFFFFFFFF
        if inverse & (inverse + 1):
            continue  # not a run of ones followed by zeros
        try:
            return str(ipaddress.ip_network("%s/%d" % (ip_text, bin(mask).count("1")), strict=False))
        except ValueError:
            continue
    return None


def lan_address(run=subprocess.run, platform=None):
    """The IPv4 address of the default route's device, from `ip -json -4 route show default` and `ip -json -4 addr show dev <dev>` (macOS: `route` and `ipconfig`).

    The route with the lowest metric wins; on a device with several addresses the route's preferred source is used when it
    names one, else the first global one. None when `ip` is missing, there is no default route or the device has no address.
    """
    if is_macos(platform):
        return _macos_lan_address(run)
    routes = _ip_json(run, ["route", "show", "default"])
    routes = [r for r in routes or [] if isinstance(r, dict) and isinstance(r.get("dev"), str) and _IFACE_RE.match(r["dev"])]
    if not routes:
        return None
    route = min(routes, key=lambda r: r["metric"] if isinstance(r.get("metric"), int) else 0)
    found = []
    for iface in _ip_json(run, ["addr", "show", "dev", route["dev"]]) or []:
        for info in (iface.get("addr_info") or []) if isinstance(iface, dict) else []:
            try:
                ip = ipaddress.IPv4Address(info["local"])
            except (KeyError, TypeError, ValueError):
                continue
            if info.get("family") == "inet" and not ip.is_unspecified:
                found.append((str(ip), info.get("scope")))
    preferred = route.get("prefsrc")
    for ip, _ in found:
        if ip == preferred:
            return ip
    for ip, scope in found:
        if scope == "global":
            return ip
    return found[0][0] if found else None


def lan_network(ip_text, run=subprocess.run, platform=None):
    """The network [ip_text] is on (`192.168.42.0/24`), from `ip -json -4 addr` (macOS: `ifconfig`), or None when that does not say."""
    if is_macos(platform):
        return _macos_lan_network(ip_text, run)
    for iface in _ip_json(run, ["addr", "show"]) or []:
        for info in (iface.get("addr_info") or []) if isinstance(iface, dict) else []:
            try:
                if info.get("family") == "inet" and info.get("local") == ip_text and isinstance(info.get("prefixlen"), int):
                    return str(ipaddress.ip_network("%s/%d" % (ip_text, info["prefixlen"]), strict=False))
            except (AttributeError, ValueError):
                continue
    return None


MACOS_FIREWALL = "/usr/libexec/ApplicationFirewall/socketfilterfw"


def _macos_firewall_note(run):
    """The macOS application firewall, read with `socketfilterfw --getglobalstate` (`... (State = 1)`: 0 off, 1 on, 2 block all incoming). Read only."""
    m = re.search(r"State\s*=\s*(\d)", _run_text(run, [MACOS_FIREWALL, "--getglobalstate"]) or "")
    state = int(m.group(1)) if m else 0
    if state == 2:
        return ("The macOS firewall is set to block all incoming connections, so the phone says it cannot reach this machine.\n"
                "  Turn 'Block all incoming connections' off for this pairing (System Settings > Network > Firewall > Options), and on again afterwards.\n")
    if state == 1:
        return ("The macOS firewall is on here. The first time this popup listens, macOS may ask whether Python may accept incoming network connections:\n"
                "  click Allow, or the phone says it cannot reach this machine. This plugin changes nothing in the firewall.\n")
    return None


def firewall_note(port, network, run=subprocess.run, platform=None):
    """What to say when a host firewall is running that drops a phone's connection to the listener's port, or None. A firewall that denies incoming
    connections (ufw's and firewalld's default) lets the phone's SYN packets die without an answer, so the phone only ever says it cannot reach the
    machine. Only ufw and firewalld are looked for, by whether their service is active (no privilege needed), and on macOS the application firewall's
    state; nothing is run that changes them. The commands are for the owner to run, for this pairing only and removed afterwards."""
    if is_macos(platform):
        return _macos_firewall_note(run)

    def active(unit):
        try:
            return run(["systemctl", "is-active", "--quiet", unit], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5).returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False
    source = " from %s" % network if network else ""
    if active("ufw"):
        return ("ufw is running here, and it drops a phone's connection to a port nobody opened, so the phone says it cannot reach this machine.\n"
                "  Open this port for this pairing, in another terminal:\n"
                "    sudo ufw allow proto tcp%s to any port %d\n"
                "  and close it afterwards:\n"
                "    sudo ufw delete allow proto tcp%s to any port %d\n" % (source, port, source, port))
    if active("firewalld"):
        return ("firewalld is running here, and it may drop a phone's connection to a port nobody opened.\n"
                "  Open this port until the next reload, in another terminal:\n"
                "    sudo firewall-cmd --add-port=%d/tcp\n"
                "  and close it afterwards:\n"
                "    sudo firewall-cmd --remove-port=%d/tcp\n" % (port, port))
    return None


def listen_address_problem(ip_text):
    """Why the listener may not bind [ip_text], or None. It is LAN-only: an IPv4 literal that is not a public address."""
    try:
        ip = ipaddress.IPv4Address(ip_text)
    except (ValueError, TypeError):
        return "The listener needs an IPv4 address."
    if ip.is_unspecified or ip.is_multicast or ip == ipaddress.IPv4Address("255.255.255.255"):
        return "The listener will not bind %s: name the one LAN address the phone can reach." % ip
    if ip.is_global:
        return "The listener is LAN-only and %s is a public address, so it stays off." % ip
    return None


class EchoOff(object):
    """Terminal echo off on [stream] while the popup waits for a pasted key line, so the line is never drawn on the screen.

    Does nothing when [stream] is not a terminal. It drops anything typed before it started and, in restore(), anything typed
    while it ran, so a stray Enter can never answer the approval prompt; restore() is also what leaving the `with` block does.
    """

    def __init__(self, stream):
        self.fd = None
        self.old = None
        try:
            import termios
            fd = stream.fileno()
            old = termios.tcgetattr(fd)
            new = termios.tcgetattr(fd)
            new[3] &= ~termios.ECHO
            termios.tcsetattr(fd, termios.TCSADRAIN, new)
            self.fd, self.old = fd, old
            termios.tcflush(fd, termios.TCIFLUSH)  # whatever was typed before the popup was ready is not an answer
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.restore()

    def restore(self):
        if self.fd is None:
            return
        import termios
        fd, self.fd = self.fd, None
        try:
            termios.tcsetattr(fd, termios.TCSADRAIN, self.old)
            termios.tcflush(fd, termios.TCIFLUSH)
        except Exception:
            pass


# ---- the pairing listener (wire grammar and state machine: PROTOCOL.md) ---------------------------------------------------------

WIRE_VERSION = "paddock-pair/1"
REPLY_WORDS = ("pending", "ok", "rejected", "expired", "refused", "busy", "none")
MAX_REQUEST_BYTES = 4096        # one request line, its "\n" included
REQUEST_TIMEOUT_S = 5.0         # from connecting to the end of the line; also the longest a connection is kept
IDLE_TIMEOUT_S = 2.0            # a connection that has sent no byte by then is closed (a phone sends at once)
MAX_CONNECTIONS = 8
MAX_PER_SOURCE = 2              # of those, from one source address (a phone has one connection at a time; the emulator's are all 127.0.0.1)
RATE_LIMIT = 12                 # counted requests per source address per rolling RATE_WINDOW_S (a correct-sid status poll is not counted)
RATE_WINDOW_S = 60.0
PAIR_WINDOW_S = 120.0
MAX_TRACKED_SOURCES = 1024


class _Conn(object):
    __slots__ = ("sock", "source", "buf", "deadline", "idle_deadline", "replied")

    def __init__(self, sock, source, deadline, idle_deadline):
        self.sock = sock
        self.source = source
        self.buf = b""
        self.deadline = deadline
        self.idle_deadline = idle_deadline  # None once the first byte has arrived
        self.replied = False


class PairListener(object):
    """The popup's LAN intake: plain TCP, one public key, a short window, and a one-word answer. Never threads, never blocking.

    It holds at most one key (a [KeyLine]) and answers with a word from REPLY_WORDS; nothing but that word ever leaves the host.
    Register it on the popup's selector with the [selector] argument (it adds its own sockets, with callables as `data`, and
    the caller runs `key.data(key.fileobj, mask)`), or call poll() to let it run its own selector. Call tick() regularly: it
    drops connections that took longer than REQUEST_TIMEOUT_S, or sent nothing in IDLE_TIMEOUT_S. [clock] is injectable for tests.

    The popup decides: adopt() hands it a key that arrived by another intake, finish() records the owner's decision. The
    request line is never logged: [log] holds only `verb -> word`.
    """

    def __init__(self, bind_ip, sid, clock=time.monotonic, window_s=PAIR_WINDOW_S, selector=None, port=0, max_connections=MAX_CONNECTIONS,
                 rate_limit=RATE_LIMIT, rate_window_s=RATE_WINDOW_S, request_timeout_s=REQUEST_TIMEOUT_S, max_per_source=MAX_PER_SOURCE,
                 idle_timeout_s=IDLE_TIMEOUT_S):
        if not isinstance(sid, str) or not SID_RE.match(sid):
            raise Refusal("The pairing handle must be 22 characters from A-Z, a-z, 0-9, _ and -.")
        problem = listen_address_problem(bind_ip)
        if problem:
            raise Refusal(problem)
        self._sid = sid.encode("ascii")
        self._clock = clock
        self.window_s = window_s
        self.max_connections = max_connections
        self.max_per_source = max_per_source
        self.idle_timeout_s = idle_timeout_s
        self.rate_limit = rate_limit
        self.rate_window_s = rate_window_s
        self.request_timeout_s = request_timeout_s
        self.held = None        # the one KeyLine this run holds, or None
        self.held_from = None   # the sender's address for a key that came over the wire, else None
        self.engaged = False    # a phone has sent the held key, or asked about it: someone is waiting for its word
        self.told = False       # the held key's final word (ok, rejected or expired) has been answered at least once
        self.log = collections.deque(maxlen=200)
        self._decided = None    # "ok" or "rejected" once the popup has decided
        self._conns = {}
        self._hits = {}
        self._closed = False
        self._own_selector = selector is None
        self._sel = selectors.DefaultSelector() if selector is None else selector
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._sock.bind((bind_ip, port))
            self._sock.listen(8)
            self._sock.setblocking(False)
        except OSError as e:
            self._sock.close()
            raise Refusal("Could not listen on %s: %s." % (bind_ip, os.strerror(e.errno) if e.errno else "I/O error"), 4)
        self.address = self._sock.getsockname()
        self.port = self.address[1]
        self.deadline = clock() + window_s
        self._sel.register(self._sock, selectors.EVENT_READ, self._on_accept)

    # -- state -----------------------------------------------------------------------------------------------------------------

    @property
    def state(self):
        """`none`, `pending`, `ok`, `rejected` or `expired` (the window ended while the held key was still undecided)."""
        if self.held is None:
            return "none"
        if self._decided:
            return self._decided
        return "expired" if self._clock() >= self.deadline else "pending"

    def adopt(self, key, source=None):
        """Holds [key], which arrived by another intake, so a phone that sends a different key is told `busy`. False if one is held."""
        if self.held is not None or self._clock() >= self.deadline:
            return False
        self.held, self.held_from = key, source
        return True

    def end_window(self):
        """Ends the window now, for a popup whose run is over with no key to decide (a refused paste or camera read): a key that
        arrives from here on is told `expired` and is not stored, because nothing will ever prompt for it. A decided key is still answered."""
        self.deadline = min(self.deadline, self._clock())

    def finish(self, approved):
        """Records the owner's decision on the held key: `ok` when [approved] is that key, `rejected` for anything else (or None)."""
        if self.held is None or self._decided:
            return
        self._decided = "ok" if approved is not None and approved.blob == self.held.blob else "rejected"

    # -- the wire --------------------------------------------------------------------------------------------------------------

    def _sid_ok(self, sid):
        return hmac.compare_digest(sid.encode("ascii"), self._sid)

    def _final(self, word):
        if word in ("ok", "rejected", "expired"):
            self.told = True
        return word

    def _process(self, line, source):
        """(verb, word) for one request line (bytes, without its "\\n"). Every failure is `refused`; nothing is echoed."""
        verb = "invalid"
        try:
            try:
                text = line.decode("ascii")
            except UnicodeDecodeError:  # never a correct status poll and never for the key check: it counts like any other malformed line
                return ("invalid", "refused") if self._admit(source) else ("limited", "busy")
            version, _, rest = text.partition(" ")
            if version == WIRE_VERSION:
                verb, _, rest = rest.partition(" ")
                if verb == "status" and self._sid_ok(rest):
                    # a status poll with the right handle is the one request that is free: a phone polling every 2 s is never throttled
                    self.engaged = self.engaged or self.held is not None
                    return verb, self._final(self.state)
            if not self._admit(source):  # everything else counts: a key, a wrong handle, a malformed line
                return "limited", "busy"
            if version == WIRE_VERSION and verb == "status":
                return verb, "refused"
            if version == WIRE_VERSION and verb == "key":
                sid, _, keyline = rest.partition(" ")
                sid_ok = self._sid_ok(sid)
                try:
                    key = parse_key_line(keyline)
                except Refusal:
                    key = None
                if not sid_ok or key is None:
                    return verb, "refused"
                return verb, self._key(key, source)
        except Exception:
            pass
        return "invalid", "refused"

    def _key(self, key, source):
        if self._clock() >= self.deadline:
            return "expired"
        if self.held is None:
            self.held, self.held_from = key, source
            self.engaged = True
            return "pending"
        if self.held.blob == key.blob:
            self.engaged = True
            return self._final(self.state)
        return "busy"

    def _admit(self, source):
        now = self._clock()
        hist = self._hits.get(source)
        if hist is None:
            if len(self._hits) >= MAX_TRACKED_SOURCES:
                self._hits = {k: v for k, v in self._hits.items() if v and now - v[-1] < self.rate_window_s}
                if len(self._hits) >= MAX_TRACKED_SOURCES:
                    return False
            hist = self._hits[source] = collections.deque()
        while hist and now - hist[0] >= self.rate_window_s:
            hist.popleft()
        if len(hist) >= self.rate_limit:
            return False
        hist.append(now)
        return True

    def _on_accept(self, sock, mask=None):
        while not self._closed:
            try:
                conn_sock, addr = self._sock.accept()
            except (BlockingIOError, InterruptedError):
                return
            except OSError:
                return
            if len(self._conns) >= self.max_connections or sum(c.source == addr[0] for c in self._conns.values()) >= self.max_per_source:
                conn_sock.close()  # no reply: the extra connection is simply closed, and never takes a slot (one address cannot fill them all)
                continue
            conn_sock.setblocking(False)
            now = self._clock()
            self._conns[conn_sock] = _Conn(conn_sock, addr[0], now + self.request_timeout_s, now + self.idle_timeout_s)
            self._sel.register(conn_sock, selectors.EVENT_READ, self._on_readable)

    def _on_readable(self, sock, mask=None):
        conn = self._conns.get(sock)
        if conn is None:
            return
        try:
            data = sock.recv(4096 if conn.replied else MAX_REQUEST_BYTES + 1 - len(conn.buf))
        except (BlockingIOError, InterruptedError):
            return
        except OSError:
            self._drop(conn)
            return
        if not data:  # the client closed: after the reply that is the normal end, before it there was no request
            self._drop(conn)
            return
        conn.idle_deadline = None
        if conn.replied:
            return  # what a client sends after its request is read and thrown away, until it closes or the deadline
        conn.buf += data
        end = conn.buf.find(b"\n")
        if 0 <= end < MAX_REQUEST_BYTES:
            self._respond(conn, conn.buf[:end])
        elif len(conn.buf) >= MAX_REQUEST_BYTES:
            self._respond(conn, None)  # no line end within 4096 bytes

    def _respond(self, conn, line):
        if line is None:  # an oversize line counts like any other request that is not a correct status poll
            verb, word = ("oversize", "refused") if self._admit(conn.source) else ("limited", "busy")
        else:
            verb, word = self._process(line, conn.source)
        self.log.append("%s -> %s" % (verb, word))
        try:
            conn.sock.send((WIRE_VERSION + " " + word + "\n").encode("ascii"))
            conn.sock.shutdown(socket.SHUT_WR)  # the client sees the line and then the end of the stream
        except OSError:
            pass
        conn.replied = True
        conn.buf = b""

    def _drop(self, conn):
        self._conns.pop(conn.sock, None)
        try:
            self._sel.unregister(conn.sock)
        except (KeyError, ValueError, OSError):
            pass
        try:
            conn.sock.close()
        except OSError:
            pass

    # -- driving ---------------------------------------------------------------------------------------------------------------

    def tick(self):
        """Drops every connection older than the request timeout, replied or not, and every one that has sent nothing within the
        idle timeout (a slow or idle client gets no reply)."""
        now = self._clock()
        for conn in list(self._conns.values()):
            if now >= conn.deadline or (conn.idle_deadline is not None and now >= conn.idle_deadline):
                self._drop(conn)

    def poll(self, timeout=0.0):
        """One round of the listener's own selector (for callers that do not run one), then tick()."""
        for key, mask in self._sel.select(timeout):
            key.data(key.fileobj, mask)
        self.tick()

    def close(self):
        """Closes the listening socket and every connection. Safe to call twice."""
        if self._closed:
            return
        self._closed = True
        for conn in list(self._conns.values()):
            self._drop(conn)
        try:
            self._sel.unregister(self._sock)
        except (KeyError, ValueError, OSError):
            pass
        self._sock.close()
        if self._own_selector:
            self._sel.close()
