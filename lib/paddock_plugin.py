"""Shared code for the Paddock herdr plugin: the phone-key line check, the authorized_keys writer and the pairing link.

Python 3.8 or newer, standard library only. Nothing here talks to the network, runs a shell or reads anything but the files
named below. The rules (and the reason for each) are in the README; the numbers and the alphabets match the Paddock app's own
copy command and pairing-link parser, so a line one accepts the other accepts.
"""
import base64
import errno
import getpass
import glob
import hashlib
import os
import re
import socket
import stat

KEY_TYPE = "ecdsa-sha2-nistp256"
CURVE = "nistp256"
MAX_INPUT_BYTES = 1024
COMMENT_RE = re.compile(r"^[A-Za-z0-9@._-]{1,64}$")
BASE64_RE = re.compile(r"^[A-Za-z0-9+/]+={0,2}$")
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

HOST_RE = re.compile(r"^[A-Za-z0-9._:\[\]-]{1,253}$")
USER_RE = re.compile(r"^[A-Za-z0-9._-]{1,32}$")
SESSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
SHA256_RE = re.compile(r"^SHA256:[A-Za-z0-9+/]{43}$")

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


def default_host():
    return socket.gethostname()


def current_user():
    try:
        return getpass.getuser()
    except Exception:
        return ""


def build_link(host, port, user, fingerprints, session=None):
    """`paddock://pair?v=1&host=…&port=…&user=…&fp=SHA256:…[,SHA256:…][&session=…]`. Refuses a field the app would refuse."""
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
    link = "paddock://pair?v=1&host=%s&port=%d&user=%s&fp=%s" % (host, port, user, ",".join(fingerprints))
    if session is not None:
        link += "&session=" + session
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
