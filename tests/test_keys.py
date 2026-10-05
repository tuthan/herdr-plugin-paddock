import base64
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

from support import BIN, GOOD_BODY, GOOD_FINGERPRINT, GOOD_LINE, OTHER_LINE
import paddock_plugin as pp

MARK = "ZZMARKERZZ"  # planted in hostile input: no refusal message may ever contain it


def blob_with(**changes):
    """The good key's blob with one part changed, as base64 text, to build malformed-but-plausible key parts."""
    raw = bytearray(base64.b64decode(GOOD_BODY))
    if "curve" in changes:
        raw[27:35] = changes["curve"]
    if "first_byte" in changes:
        raw[39] = changes["first_byte"]
    if "append" in changes:
        raw += changes["append"]
    if "truncate" in changes:
        raw = raw[:changes["truncate"]]
    if "type_name" in changes:
        raw[4:23] = changes["type_name"]
    return base64.b64encode(bytes(raw)).decode()


HOSTILE = [
    # (name, input, a fragment the refusal must contain)
    ("empty", "", "Nothing was pasted"),
    ("only a newline", "\n", "Nothing was pasted"),
    ("only spaces", "   ", "spaces"),
    ("two lines", GOOD_LINE + "\n" + GOOD_LINE, "more than one line"),
    ("two lines, CRLF between", GOOD_LINE + "\r\n" + GOOD_LINE, "more than one line"),
    ("second line after the terminator", GOOD_LINE + "\n\n", "more than one line"),
    ("a lone CR in the middle", "ecdsa-sha2-nistp256\r" + GOOD_BODY, "more than one line"),
    ("a NUL byte", GOOD_LINE + "\x00", "characters a key line never has"),
    ("a tab", "ecdsa-sha2-nistp256\t" + GOOD_BODY, "characters a key line never has"),
    ("an escape", "\x1b[31m" + GOOD_LINE, "characters a key line never has"),
    ("DEL", GOOD_LINE + "\x7f", "characters a key line never has"),
    ("non-ASCII comment", GOOD_LINE + "é", "characters a key line never has"),
    ("leading space", " " + GOOD_LINE, "spaces before and after"),
    ("trailing space", GOOD_LINE + " ", "spaces before and after"),
    ("double space", "ecdsa-sha2-nistp256  " + GOOD_BODY, "single spaces"),
    ("four fields", GOOD_LINE + " " + MARK, "single spaces"),
    ("one field", "ecdsa-sha2-nistp256", "single spaces"),
    ("option prefix command=", 'command="' + MARK + '" ' + GOOD_LINE, "Nothing may come before the key type"),
    ("option prefix from=", 'from="10.0.0.0/8" ' + GOOD_LINE, "Nothing may come before the key type"),
    ("option prefix no-pty,", "no-pty," + GOOD_LINE, "Nothing may come before the key type"),
    ("ed25519", "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI" + MARK + " x", "Only ecdsa-sha2-nistp256"),
    ("rsa", "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABgQ" + MARK + " x", "Only ecdsa-sha2-nistp256"),
    ("ecdsa 384", "ecdsa-sha2-nistp384 " + GOOD_BODY + " x", "Only ecdsa-sha2-nistp256"),
    ("a certificate type", "ecdsa-sha2-nistp256-cert-v01@openssh.com " + GOOD_BODY, "Only ecdsa-sha2-nistp256"),
    ("upper-case type", "ECDSA-SHA2-NISTP256 " + GOOD_BODY, "Only ecdsa-sha2-nistp256"),
    ("a PEM private key", "-----BEGIN OPENSSH PRIVATE KEY-----\n" + MARK + "\n-----END OPENSSH PRIVATE KEY-----\n", "private key"),
    ("a one-line private key header", "-----BEGIN EC PRIVATE KEY-----", "private key"),
    ("an RSA PEM, long", "-----BEGIN RSA PRIVATE KEY-----\n" + ("A" * 64 + "\n") * 40 + MARK, "private key"),
    ("a PuTTY key file", "PuTTY-User-Key-File-3: ecdsa-sha2-nistp256\nEncryption: none\n" + MARK, "private key"),
    ("PRIVATE KEY inside a plausible line", "ecdsa-sha2-nistp256 " + GOOD_BODY + " PRIVATE KEY", "private key"),
    ("base64 with bad characters", "ecdsa-sha2-nistp256 " + GOOD_BODY[:-4] + "!!!!" + " x", "not valid base64"),
    ("base64 with the wrong length", "ecdsa-sha2-nistp256 " + GOOD_BODY[:-1] + " x", "not valid base64"),
    ("base64 with padding in the middle", "ecdsa-sha2-nistp256 " + GOOD_BODY[:10] + "=" + GOOD_BODY[11:] + " x", "not valid base64"),
    ("the other curve's name in the blob", "ecdsa-sha2-nistp256 " + blob_with(curve=b"nistp384") + " x", "not a P-256 public key"),
    ("a wrong type name inside the blob", "ecdsa-sha2-nistp256 " + blob_with(type_name=b"ecdsa-sha2-nistp384") + " x", "not a P-256 public key"),
    ("an uncompressed-point byte that is not 04", "ecdsa-sha2-nistp256 " + blob_with(first_byte=0x02) + " x", "not a P-256 public key"),
    ("a blob with a trailing byte", "ecdsa-sha2-nistp256 " + blob_with(append=b"\x00") + " x", "not a P-256 public key"),
    ("a truncated blob", "ecdsa-sha2-nistp256 " + blob_with(truncate=60) + " x", "not a P-256 public key"),
    ("an empty key part", "ecdsa-sha2-nistp256  x", "single spaces"),
    ("comment of 65 characters", GOOD_LINE.rsplit(" ", 1)[0] + " " + "a" * 65, "comment may be up to 64"),
    ("comment with a semicolon", GOOD_LINE.rsplit(" ", 1)[0] + " a;" + MARK, "comment may be up to 64"),
    ("comment with a command substitution", GOOD_LINE.rsplit(" ", 1)[0] + " $(" + MARK + ")", "comment may be up to 64"),
    ("comment with a backtick", GOOD_LINE.rsplit(" ", 1)[0] + " `" + MARK + "`", "comment may be up to 64"),
    ("comment with a quote", GOOD_LINE.rsplit(" ", 1)[0] + " a'b" + MARK, "comment may be up to 64"),
    ("comment with a double quote", GOOD_LINE.rsplit(" ", 1)[0] + ' a"b' + MARK, "comment may be up to 64"),
    ("comment with an equals sign", GOOD_LINE.rsplit(" ", 1)[0] + " a=b" + MARK, "comment may be up to 64"),
    ("comment with a slash", GOOD_LINE.rsplit(" ", 1)[0] + " a/b" + MARK, "comment may be up to 64"),
    ("1025 bytes of A", "A" * 1025, "too long"),
    ("a megabyte", "A" * (1 << 20), "too long"),
    ("a valid line padded past the cap", GOOD_LINE + " " + "b" * 1100, "too long"),
]


def non_canonical_bodies():
    """The good key's base64 with each of the other three last characters that decode to the same blob (the last character of a
    padded body carries bits that decoding drops). OpenSSH, and the app's re-encoding parser, refuse all three."""
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
    assert GOOD_BODY.endswith("=") and not GOOD_BODY.endswith("==")  # two spare bits in the last character
    head, last = GOOD_BODY[:-2], GOOD_BODY[-2]
    first = alphabet.index(last) & ~3
    out = [head + alphabet[first + n] + "=" for n in range(4) if alphabet[first + n] != last]
    assert len(out) == 3 and all(base64.b64decode(b, validate=True) == base64.b64decode(GOOD_BODY) for b in out)
    return out


class ParseKeyLine(unittest.TestCase):
    def test_the_reference_key_line_is_accepted_and_has_the_fingerprint_ssh_keygen_prints(self):
        key = pp.parse_key_line(GOOD_LINE)
        self.assertEqual(GOOD_LINE, key.line)
        self.assertEqual("paddock@phone", key.comment)
        self.assertEqual(GOOD_FINGERPRINT, key.fingerprint)

    @unittest.skipUnless(shutil.which("ssh-keygen"), "ssh-keygen not installed")
    def test_fingerprints_equal_ssh_keygens_for_freshly_made_keys(self):
        with tempfile.TemporaryDirectory() as d:
            for n in range(3):
                path = os.path.join(d, "k%d" % n)
                subprocess.check_call(["ssh-keygen", "-q", "-t", "ecdsa", "-b", "256", "-N", "", "-C", "t%d@h" % n, "-f", path])
                with open(path + ".pub") as f:
                    line = f.read().strip()
                out = subprocess.check_output(["ssh-keygen", "-lf", path + ".pub"]).decode().split()
                key = pp.parse_key_line(line)
                self.assertEqual(out[1], key.fingerprint)

    def test_accepted_shapes(self):
        for name, data, comment in [
            ("one trailing LF", GOOD_LINE + "\n", "paddock@phone"),
            ("one trailing CRLF", GOOD_LINE + "\r\n", "paddock@phone"),
            ("bytes", (GOOD_LINE + "\n").encode(), "paddock@phone"),
            ("no comment", "ecdsa-sha2-nistp256 " + GOOD_BODY, None),
            ("every allowed comment character", "ecdsa-sha2-nistp256 " + GOOD_BODY + " aZ09@._-", "aZ09@._-"),
            ("a comment of 64 characters", "ecdsa-sha2-nistp256 " + GOOD_BODY + " " + "a" * 64, "a" * 64),
            ("a comment of 1 character", "ecdsa-sha2-nistp256 " + GOOD_BODY + " a", "a"),
        ]:
            with self.subTest(name):
                key = pp.parse_key_line(data)
                self.assertEqual(comment, key.comment)
                self.assertEqual(GOOD_FINGERPRINT, key.fingerprint)

    def test_every_hostile_input_is_refused_with_the_right_reason_and_never_echoed(self):
        for name, data, fragment in HOSTILE:
            with self.subTest(name):
                with self.assertRaises(pp.Refusal) as ctx:
                    pp.parse_key_line(data)
                message = ctx.exception.message
                self.assertIn(fragment, message)
                self.assertNotIn(MARK, message, "the refusal repeats the input")
                self.assertNotIn(GOOD_BODY[:30], message, "the refusal repeats the key")
                self.assertEqual(2, ctx.exception.code)
                self.assertIn("Nothing was written", message)

    def test_a_non_canonical_base64_key_part_is_refused_and_only_the_canonical_form_passes(self):
        # b64decode(validate=True) drops the unused trailing bits, so all four spellings decode to one blob; ssh-keygen -l accepts
        # one of them ("not a public key file" for the rest) and the app re-encodes and compares, so the canonical spelling is the only one
        for body in non_canonical_bodies():
            for tail in ("", " paddock@phone"):
                with self.subTest(body=body[-4:], comment=bool(tail)):
                    with self.assertRaises(pp.Refusal) as ctx:
                        pp.parse_key_line("ecdsa-sha2-nistp256 " + body + tail)
                    self.assertIn("not valid base64", ctx.exception.message)
                    self.assertIn("Nothing was written", ctx.exception.message)
                    self.assertNotIn(body, ctx.exception.message)
        self.assertEqual(GOOD_FINGERPRINT, pp.parse_key_line(GOOD_LINE).fingerprint)

    @unittest.skipUnless(shutil.which("ssh-keygen"), "ssh-keygen not installed")
    def test_the_canonical_check_agrees_with_ssh_keygen_on_every_spelling(self):
        with tempfile.TemporaryDirectory() as d:
            for body in [GOOD_BODY] + non_canonical_bodies():
                path = os.path.join(d, "k.pub")
                with open(path, "w") as f:
                    f.write("ecdsa-sha2-nistp256 " + body + " t@h\n")
                reads = subprocess.run(["ssh-keygen", "-lf", path], stdout=subprocess.PIPE, stderr=subprocess.PIPE).returncode == 0
                try:
                    pp.parse_key_line("ecdsa-sha2-nistp256 " + body + " t@h")
                    accepts = True
                except pp.Refusal:
                    accepts = False
                self.assertEqual(reads, accepts, body[-4:])

    def test_a_valid_line_is_never_taken_for_a_private_key(self):
        # The private-key wording is only chosen for input refused anyway, so a key whose text contains a marker is not refused for it.
        body = GOOD_BODY
        self.assertEqual(GOOD_FINGERPRINT, pp.parse_key_line("ecdsa-sha2-nistp256 " + body + " BEGIN").fingerprint)


class Authorize(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = self._tmp.name
        self.ssh = os.path.join(self.home, ".ssh")
        self.ak = os.path.join(self.ssh, "authorized_keys")
        self.key = pp.parse_key_line(GOOD_LINE)

    def tearDown(self):
        for dirpath, dirnames, filenames in os.walk(self.home):
            for n in dirnames + filenames:
                p = os.path.join(dirpath, n)
                if not os.path.islink(p):
                    try:
                        os.chmod(p, 0o700)
                    except OSError:
                        pass
        self._tmp.cleanup()

    def mode(self, path):
        return stat.S_IMODE(os.lstat(path).st_mode)

    def read(self, path=None):
        with open(path or self.ak, "rb") as f:
            return f.read()

    def write(self, data, mode=0o600):
        os.makedirs(self.ssh, mode=0o700, exist_ok=True)
        with open(self.ak, "wb") as f:
            f.write(data)
        os.chmod(self.ak, mode)

    def test_from_nothing_it_creates_ssh_700_and_the_file_600_with_exactly_the_line(self):
        result = pp.authorize(self.home, self.key)
        self.assertEqual("added", result.status)
        self.assertEqual(self.ak, result.path)
        self.assertEqual(GOOD_FINGERPRINT, result.fingerprint)
        self.assertEqual(0o700, self.mode(self.ssh))
        self.assertEqual(0o600, self.mode(self.ak))
        self.assertEqual((GOOD_LINE + "\n").encode(), self.read())

    def test_run_five_times_the_line_is_there_once(self):
        results = [pp.authorize(self.home, self.key).status for _ in range(5)]
        self.assertEqual(["added", "already", "already", "already", "already"], results)
        self.assertEqual(1, self.read().split(b"\n").count(GOOD_LINE.encode()))
        self.assertEqual((GOOD_LINE + "\n").encode(), self.read())

    def test_other_lines_are_untouched_byte_for_byte_and_the_new_line_goes_after_them(self):
        original = b"# my keys\nssh-ed25519 AAAAC3Nza-other-key someone@laptop\r\ncommand=\"/bin/true\" ssh-rsa AAAAB3Nza-x y\n\n"
        self.write(original)
        self.assertEqual("added", pp.authorize(self.home, self.key).status)
        self.assertEqual(original + GOOD_LINE.encode() + b"\n", self.read())

    def test_a_file_without_a_trailing_newline_gets_one_before_the_line_and_nothing_else_changes(self):
        original = b"ssh-ed25519 AAAAC3Nza-other-key someone@laptop"
        self.write(original)
        pp.authorize(self.home, self.key)
        self.assertEqual(original + b"\n" + GOOD_LINE.encode() + b"\n", self.read())

    def test_an_empty_existing_file_gets_no_leading_blank_line(self):
        self.write(b"")
        pp.authorize(self.home, self.key)
        self.assertEqual((GOOD_LINE + "\n").encode(), self.read())

    def test_the_result_always_starts_with_the_original_bytes(self):
        for original in (b"", b"a", b"a\n", b"a\nb", b"\n", b"\n\n", b"x\r\n", b"\xff\xfe binary \x00 junk"):
            with self.subTest(original=original):
                shutil.rmtree(self.ssh, ignore_errors=True)
                self.write(original)
                pp.authorize(self.home, self.key)
                self.assertTrue(self.read().startswith(original))
                self.assertTrue(self.read().endswith(GOOD_LINE.encode() + b"\n"))

    def test_a_line_that_differs_only_in_its_comment_is_a_different_line(self):
        self.write((OTHER_LINE + "\n").encode())
        self.assertEqual("added", pp.authorize(self.home, self.key).status)
        self.assertEqual(((OTHER_LINE + "\n") + GOOD_LINE + "\n").encode(), self.read())

    def test_loose_modes_that_are_not_writable_are_tightened(self):
        os.mkdir(self.ssh, 0o755)
        os.chmod(self.ssh, 0o755)
        self.write(b"x\n", 0o644)
        os.chmod(self.ssh, 0o755)
        pp.authorize(self.home, self.key)
        self.assertEqual(0o700, self.mode(self.ssh))
        self.assertEqual(0o600, self.mode(self.ak))

    def test_the_already_there_case_still_sets_the_modes(self):
        self.write((GOOD_LINE + "\n").encode(), 0o640)
        self.assertEqual("already", pp.authorize(self.home, self.key).status)
        self.assertEqual(0o600, self.mode(self.ak))

    def test_a_symlinked_ssh_directory_is_refused_and_its_target_untouched(self):
        target = os.path.join(self.home, "elsewhere")
        os.mkdir(target, 0o700)
        os.symlink(target, self.ssh)
        with self.assertRaises(pp.Refusal) as ctx:
            pp.authorize(self.home, self.key)
        self.assertEqual(3, ctx.exception.code)
        self.assertIn("symbolic link", ctx.exception.message)
        self.assertEqual([], os.listdir(target))

    def test_a_symlinked_authorized_keys_is_refused_and_its_target_untouched(self):
        os.mkdir(self.ssh, 0o700)
        target = os.path.join(self.home, "managed_keys")
        with open(target, "wb") as f:
            f.write(b"managed\n")
        os.symlink(target, self.ak)
        with self.assertRaises(pp.Refusal) as ctx:
            pp.authorize(self.home, self.key)
        self.assertIn("symbolic link", ctx.exception.message)
        self.assertEqual(b"managed\n", self.read(target))
        self.assertTrue(os.path.islink(self.ak))

    def test_a_dangling_symlink_is_refused_too(self):
        os.mkdir(self.ssh, 0o700)
        os.symlink(os.path.join(self.home, "missing"), self.ak)
        with self.assertRaises(pp.Refusal):
            pp.authorize(self.home, self.key)
        self.assertFalse(os.path.exists(os.path.join(self.home, "missing")))

    def test_group_or_world_writable_directory_or_file_is_refused_and_nothing_changes(self):
        for what, mode in (("dir", 0o770), ("dir", 0o707), ("dir", 0o777), ("file", 0o660), ("file", 0o606), ("file", 0o666)):
            with self.subTest(what=what, mode=oct(mode)):
                shutil.rmtree(self.ssh, ignore_errors=True)
                self.write(b"keep me\n")
                subject = self.ssh if what == "dir" else self.ak
                os.chmod(subject, mode)
                with self.assertRaises(pp.Refusal) as ctx:
                    pp.authorize(self.home, self.key)
                self.assertEqual(3, ctx.exception.code)
                self.assertIn("writable by group or others", ctx.exception.message)
                self.assertEqual(mode, self.mode(subject), "a refusal does not tighten the mode either")
                os.chmod(self.ssh, 0o700)
                self.assertEqual(b"keep me\n", self.read())

    def test_not_a_directory_or_not_a_file_is_refused(self):
        with open(self.ssh, "w") as f:
            f.write("a file where the directory should be")
        with self.assertRaises(pp.Refusal) as ctx:
            pp.authorize(self.home, self.key)
        self.assertIn("not a directory", ctx.exception.message)
        os.remove(self.ssh)
        os.makedirs(self.ak, mode=0o700)
        with self.assertRaises(pp.Refusal) as ctx:
            pp.authorize(self.home, self.key)
        self.assertIn("not a regular file", ctx.exception.message)

    def test_a_refusal_creates_nothing(self):
        # parse first, write second: bad input must not even create ~/.ssh
        with self.assertRaises(pp.Refusal):
            pp.authorize(self.home, pp.parse_key_line(GOOD_LINE + " extra"))
        self.assertFalse(os.path.exists(self.ssh))

    def test_an_unwritable_home_is_a_refusal_not_a_traceback(self):
        os.chmod(self.home, 0o500)
        try:
            with self.assertRaises(pp.Refusal) as ctx:
                pp.authorize(self.home, self.key)
            self.assertEqual(4, ctx.exception.code)
            self.assertIn("Could not update", ctx.exception.message)
        finally:
            os.chmod(self.home, 0o700)


class AuthorizeCli(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def run_cli(self, data, *extra):
        return subprocess.run([sys.executable, os.path.join(BIN, "authorize_phone.py"), "--stdin", "--home", self.home] + list(extra),
                              input=data if isinstance(data, bytes) else data.encode(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20)

    def test_a_good_line_exits_zero_and_says_what_it_did(self):
        r = self.run_cli(GOOD_LINE + "\n")
        self.assertEqual(0, r.returncode, r.stderr)
        out = r.stdout.decode()
        self.assertIn(GOOD_FINGERPRINT, out)
        self.assertIn(os.path.join(self.home, ".ssh", "authorized_keys"), out)
        self.assertIn("Nothing else in the file was changed", out)
        self.assertNotIn(GOOD_BODY, out + r.stderr.decode(), "the key itself is not echoed")
        r2 = self.run_cli(GOOD_LINE)
        self.assertEqual(0, r2.returncode)
        self.assertIn("already authorized", r2.stdout.decode())

    def test_every_hostile_input_exits_two_creates_nothing_and_echoes_nothing(self):
        for name, data, fragment in HOSTILE:
            with self.subTest(name):
                r = self.run_cli(data)
                self.assertEqual(2, r.returncode)
                text = (r.stdout + r.stderr).decode()
                self.assertIn(fragment, text)
                self.assertNotIn(MARK, text)
                self.assertFalse(os.path.exists(os.path.join(self.home, ".ssh")), "a refused line created ~/.ssh")

    def test_without_a_terminal_and_without_stdin_it_refuses_to_guess(self):
        r = subprocess.run([sys.executable, os.path.join(BIN, "authorize_phone.py"), "--home", self.home], stdin=subprocess.DEVNULL,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20)
        self.assertEqual(2, r.returncode)
        self.assertIn("no terminal", r.stderr.decode())
        self.assertFalse(os.path.exists(os.path.join(self.home, ".ssh")))

    def test_a_symlink_refusal_exits_three(self):
        target = os.path.join(self.home, "t")
        os.mkdir(target)
        os.symlink(target, os.path.join(self.home, ".ssh"))
        r = self.run_cli(GOOD_LINE)
        self.assertEqual(3, r.returncode)
        self.assertEqual([], os.listdir(target))


@unittest.skipUnless(sys.platform.startswith("linux"), "pty test is Linux-only")
class AuthorizePopup(unittest.TestCase):
    """The popup asks on a real terminal with echo off, so what is pasted is never drawn on the screen."""

    def drive(self, typed):
        import pty
        import select
        import time
        tmp = tempfile.mkdtemp()
        try:
            pid, fd = pty.fork()
            if pid == 0:
                os.execv(sys.executable, [sys.executable, os.path.join(BIN, "authorize_phone.py"), "--home", tmp])
            screen = b""

            def pump(seconds):
                nonlocal screen
                end = time.time() + seconds
                while time.time() < end:
                    r, _, _ = select.select([fd], [], [], 0.1)
                    if r:
                        try:
                            d = os.read(fd, 65536)
                        except OSError:
                            return
                        if not d:
                            return
                        screen += d

            pump(1.0)
            os.write(fd, typed.encode() + b"\n")
            pump(1.0)
            os.write(fd, b"\n")  # Enter closes the popup
            pump(1.0)
            _, status = os.waitpid(pid, 0)
            ak = os.path.join(tmp, ".ssh", "authorized_keys")
            return screen.decode("utf-8", "replace"), os.waitstatus_to_exitcode(status), (open(ak, "rb").read() if os.path.exists(ak) else None)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_a_pasted_key_line_is_not_drawn_and_is_written(self):
        screen, code, written = self.drive(GOOD_LINE)
        self.assertEqual(0, code)
        self.assertEqual((GOOD_LINE + "\n").encode(), written)
        self.assertNotIn(GOOD_BODY[:40], screen, "the pasted line was echoed to the screen")
        self.assertIn(GOOD_FINGERPRINT, screen)
        self.assertIn("Authorized this phone key", screen)

    def test_a_pasted_private_key_is_refused_and_never_drawn(self):
        screen, code, written = self.drive("-----BEGIN OPENSSH PRIVATE KEY-----" + MARK)
        self.assertEqual(2, code)
        self.assertIsNone(written)
        self.assertNotIn(MARK, screen)
        self.assertNotIn("BEGIN OPENSSH", screen)
        self.assertIn("looks like a private key", screen)


if __name__ == "__main__":
    unittest.main()
