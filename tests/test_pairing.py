import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

from support import BIN, GOOD_BODY
import paddock_plugin as pp

FP = "SHA256:" + "A" * 43
FP2 = "SHA256:" + "b" * 42 + "+"


def parse_link(link):
    """A reference reader for the contract, written independently of build_link: scheme and host, then &-separated key=value."""
    assert link.startswith("paddock://pair?")
    pairs = [p.split("=", 1) for p in link[len("paddock://pair?"):].split("&")]
    out = dict(pairs)
    assert len(out) == len(pairs), "a repeated key"
    return out


class BuildLink(unittest.TestCase):
    def test_the_contract_shape_and_order(self):
        link = pp.build_link("box.example.net", 2222, "alice", [FP, FP2], "work")
        self.assertEqual("paddock://pair?v=1&host=box.example.net&port=2222&user=alice&fp=%s,%s&session=work" % (FP, FP2), link)
        fields = parse_link(link)
        self.assertEqual(["v", "host", "port", "user", "fp", "session"], list(fields))
        self.assertEqual([FP, FP2], fields["fp"].split(","))

    def test_no_session_means_no_session_field_and_the_link_holds_no_key_material(self):
        link = pp.build_link("10.0.0.2", 22, "alice", [FP])
        self.assertNotIn("session", link)
        self.assertNotIn("ecdsa", link)
        self.assertNotIn(GOOD_BODY[:20], link)
        self.assertNotIn("key=", link)

    def test_the_ipv6_literal_form_is_allowed(self):
        self.assertIn("host=[fe80::1]", pp.build_link("[fe80::1]", 22, "u", [FP]))

    def test_fields_the_app_would_refuse_are_refused_here(self):
        bad = [
            ("host with a slash", dict(host="a/b")), ("host with a question mark", dict(host="a?b")), ("host with an ampersand", dict(host="a&b")),
            ("host with a hash", dict(host="a#b")), ("host with a space", dict(host="a b")), ("empty host", dict(host="")),
            ("host of 254 characters", dict(host="a" * 254)), ("host with a percent escape", dict(host="a%2Fb")), ("host with a newline", dict(host="a\nb")),
            ("port 0", dict(port=0)), ("port 65536", dict(port=65536)), ("a string port", dict(port="22")), ("a negative port", dict(port=-1)),
            ("empty user", dict(user="")), ("user with a space", dict(user="a b")), ("user of 33 characters", dict(user="u" * 33)), ("user with @", dict(user="a@b")),
            ("session starting with a dot", dict(session=".x")), ("session with a slash", dict(session="a/b")), ("session of 65 characters", dict(session="s" * 65)),
            ("no fingerprints", dict(fingerprints=[])), ("five fingerprints", dict(fingerprints=[FP] * 5)),
            ("a lower-case sha256 prefix", dict(fingerprints=["sha256:" + "A" * 43])), ("a short fingerprint", dict(fingerprints=["SHA256:abc"])),
            ("a fingerprint with a comma", dict(fingerprints=["SHA256:" + "A" * 42 + ","])), ("a padded fingerprint", dict(fingerprints=["SHA256:" + "A" * 43 + "="])),
            ("host with a trailing newline", dict(host="box\n")), ("user with a trailing newline", dict(user="alice\n")),
            ("session with a trailing newline", dict(session="work\n")), ("fingerprint with a trailing newline", dict(fingerprints=["SHA256:" + "A" * 43 + "\n"])),
        ]
        for name, change in bad:
            with self.subTest(name):
                args = dict(host="box", port=22, user="alice", fingerprints=[FP], session=None)
                args.update(change)
                with self.assertRaises(pp.Refusal):
                    pp.build_link(**args)

    def test_no_pattern_lets_a_trailing_newline_through(self):
        # `$` matches before a final newline; every pattern here ends in \\Z, so the newline is refused where it would reach a link or a file
        for name, rx, good in [("HOST_RE", pp.HOST_RE, "box"), ("USER_RE", pp.USER_RE, "alice"), ("SESSION_RE", pp.SESSION_RE, "work"),
                               ("SHA256_RE", pp.SHA256_RE, FP), ("COMMENT_RE", pp.COMMENT_RE, "paddock@phone"), ("BASE64_RE", pp.BASE64_RE, GOOD_BODY),
                               ("SID_RE", pp.SID_RE, "A" * 22)]:
            with self.subTest(name):
                self.assertTrue(rx.match(good))
                self.assertIsNone(rx.match(good + "\n"))

    def test_four_fingerprints_are_the_most(self):
        self.assertEqual(4, len(parse_link(pp.build_link("b", 22, "u", [FP] * 4))["fp"].split(",")))


@unittest.skipUnless(shutil.which("ssh-keygen"), "ssh-keygen not installed")
class HostKeys(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        for name, args in (("ed25519", ["-t", "ed25519"]), ("ecdsa", ["-t", "ecdsa", "-b", "256"]), ("rsa", ["-t", "rsa", "-b", "2048"])):
            subprocess.check_call(["ssh-keygen", "-q", "-N", "", "-C", "t@h", "-f", os.path.join(cls.dir, "ssh_host_%s_key" % name)] + args)
        cls.extra = tempfile.mkdtemp()  # all five types
        for name, args in (("ed25519", ["-t", "ed25519"]), ("ecdsa", ["-t", "ecdsa", "-b", "256"]), ("rsa", ["-t", "rsa", "-b", "2048"])):
            shutil.copy(os.path.join(cls.dir, "ssh_host_%s_key.pub" % name), cls.extra)
        for bits in (384, 521):
            subprocess.check_call(["ssh-keygen", "-q", "-N", "", "-C", "t@h", "-t", "ecdsa", "-b", str(bits), "-f", os.path.join(cls.extra, "k%d" % bits)])
            os.rename(os.path.join(cls.extra, "k%d.pub" % bits), os.path.join(cls.extra, "ssh_host_ecdsa%d_key.pub" % bits))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)
        shutil.rmtree(cls.extra, ignore_errors=True)

    def keygen(self, path):
        return subprocess.check_output(["ssh-keygen", "-lf", path]).decode().split()[1]

    def test_fingerprints_equal_what_ssh_keygen_prints_and_come_in_the_contract_order(self):
        got = pp.read_host_key_fingerprints(self.dir)
        self.assertEqual(["ED25519", "ECDSA P-256", "RSA"], [n for n, _, _ in got])
        for name, ktype, fp in got:
            path = os.path.join(self.dir, {"ssh-ed25519": "ssh_host_ed25519_key.pub", "ecdsa-sha2-nistp256": "ssh_host_ecdsa_key.pub", "ssh-rsa": "ssh_host_rsa_key.pub"}[ktype])
            self.assertEqual(self.keygen(path), fp, name)

    def test_with_all_five_types_four_are_kept_and_rsa_stays_over_p521(self):
        got = pp.read_host_key_fingerprints(self.extra)
        self.assertEqual(["ssh-ed25519", "ecdsa-sha2-nistp256", "ecdsa-sha2-nistp384", "ssh-rsa"], [t for _, t, _ in got])
        # the dropped type is the largest curve
        self.assertNotIn("ecdsa-sha2-nistp521", [t for _, t, _ in got])

    def test_files_that_are_not_host_keys_are_skipped(self):
        d = tempfile.mkdtemp()
        try:
            self.assertEqual([], pp.read_host_key_fingerprints(d))
            self.assertEqual([], pp.read_host_key_fingerprints(os.path.join(d, "missing")))
            with open(os.path.join(d, "ssh_host_ed25519_key.pub"), "w") as f:
                f.write("not a key at all")
            with open(os.path.join(d, "ssh_host_ecdsa_key.pub"), "w") as f:
                f.write("ecdsa-sha2-nistp256 %%%not-base64%%% x")
            # a key whose type word and blob disagree is not something sshd presents
            shutil.copy(os.path.join(self.dir, "ssh_host_rsa_key.pub"), os.path.join(d, "ssh_host_rsa_key.pub"))
            with open(os.path.join(d, "ssh_host_rsa_key.pub")) as f:
                text = f.read().replace("ssh-rsa", "ssh-ed25519", 1)
            with open(os.path.join(d, "ssh_host_rsa_key.pub"), "w") as f:
                f.write(text)
            # a certificate file and an unknown (post-quantum) type are ignored
            shutil.copy(os.path.join(self.dir, "ssh_host_ed25519_key.pub"), os.path.join(d, "ssh_host_ed25519_key-cert.pub"))
            with open(os.path.join(d, "ssh_host_mldsa44_ed25519_key.pub"), "w") as f:
                f.write("ssh-mldsa44-ed25519 AAAA x")
            self.assertEqual([], pp.read_host_key_fingerprints(d))
        finally:
            shutil.rmtree(d, ignore_errors=True)


class SshdPort(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.d = self._tmp.name
        self.conf = os.path.join(self.d, "sshd_config")
        self.conf_d = os.path.join(self.d, "sshd_config.d")
        os.mkdir(self.conf_d)

    def tearDown(self):
        self._tmp.cleanup()

    def w(self, path, text):
        with open(path, "w") as f:
            f.write(text)

    def port(self):
        return pp.sshd_port(self.conf, self.conf_d)

    def test_defaults_and_the_first_uncommented_port_wins(self):
        self.assertEqual(22, pp.sshd_port(os.path.join(self.d, "missing"), os.path.join(self.d, "missing.d")))
        self.w(self.conf, "#Port 2200\n  # Port 2201\nPermitRootLogin no\n")
        self.assertEqual(22, self.port())
        self.w(self.conf, "#Port 2200\nPort 2222 # the real one\nPort 2223\n")
        self.assertEqual(2222, self.port())
        self.w(self.conf, "Port=2022\n")
        self.assertEqual(2022, self.port())
        self.w(self.conf, "port 2121\n")
        self.assertEqual(2121, self.port())

    def test_invalid_values_are_ignored(self):
        self.w(self.conf, "Port abc\nPort 0\nPort 70000\nPort\nPort 2020\n")
        self.assertEqual(2020, self.port())

    def test_an_include_is_followed_where_it_stands_as_sshd_does(self):
        self.w(os.path.join(self.conf_d, "10-a.conf"), "Port 2300\n")
        self.w(self.conf, "Include %s/*.conf\nPort 2400\n" % self.conf_d)
        self.assertEqual(2300, self.port(), "the include comes first, so its value is the first one sshd reads")
        self.w(self.conf, "Port 2400\nInclude %s/*.conf\n" % self.conf_d)
        self.assertEqual(2400, self.port())

    def test_a_relative_include_is_relative_to_the_config_directory(self):
        self.w(os.path.join(self.conf_d, "10-a.conf"), "Port 2301\n")
        self.w(self.conf, "Include sshd_config.d/*.conf\n")
        self.assertEqual(2301, self.port())

    def test_the_conf_d_files_are_read_when_the_main_file_has_none_and_no_include(self):
        self.w(self.conf, "PermitRootLogin no\n")
        self.w(os.path.join(self.conf_d, "20-b.conf"), "Port 2500\n")
        self.w(os.path.join(self.conf_d, "10-a.conf"), "Port 2501\n")
        self.assertEqual(2501, self.port(), "in file-name order")

    def test_nothing_after_match_counts(self):
        self.w(self.conf, "Match User bob\nPort 2600\n")
        self.assertEqual(22, self.port())

    def test_an_include_loop_ends(self):
        self.w(self.conf, "Include %s\n" % self.conf)
        self.assertEqual(22, self.port())


class SessionAndUser(unittest.TestCase):
    def test_the_named_session_from_the_environment_else_from_the_socket_path_else_none(self):
        self.assertEqual("work", pp.herdr_session({"HERDR_SESSION": "work", "HERDR_SOCKET_PATH": "/x/sessions/other/herdr.sock"}))
        self.assertEqual("work", pp.herdr_session({"HERDR_SOCKET_PATH": "/data/herdr/sessions/work/herdr.sock"}))
        self.assertIsNone(pp.herdr_session({"HERDR_SOCKET_PATH": "/data/herdr/herdr.sock"}))
        self.assertIsNone(pp.herdr_session({}))


@unittest.skipUnless(shutil.which("ssh-keygen"), "ssh-keygen not installed")
class ShowPairingCli(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ssh = tempfile.mkdtemp()
        subprocess.check_call(["ssh-keygen", "-q", "-N", "", "-C", "t@h", "-t", "ed25519", "-f", os.path.join(cls.ssh, "ssh_host_ed25519_key")])
        cls.fp = subprocess.check_output(["ssh-keygen", "-lf", os.path.join(cls.ssh, "ssh_host_ed25519_key.pub")]).decode().split()[1]

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.ssh, ignore_errors=True)

    def run_cli(self, *args, **env):
        e = {k: v for k, v in os.environ.items() if not k.startswith("HERDR_")}
        e.update(env)
        return subprocess.run([sys.executable, os.path.join(BIN, "show_pairing.py"), "--no-prompt"] + list(args), env=e, stdin=subprocess.DEVNULL,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)

    def link_of(self, out):
        return [l for l in out.decode().splitlines() if l.startswith("paddock://")][0]

    def test_it_prints_the_contract_link_and_says_the_phone_must_reach_the_host(self):
        r = self.run_cli("--host", "box.example.net", "--port", "2222", "--user", "alice", "--ssh-dir", self.ssh, "--no-qr", HERDR_SESSION="work")
        self.assertEqual(0, r.returncode, r.stderr)
        link = self.link_of(r.stdout)
        self.assertEqual("paddock://pair?v=1&host=box.example.net&port=2222&user=alice&fp=%s&session=work" % self.fp, link)
        self.assertIn("the phone must be able to reach this name or address", r.stdout.decode())
        self.assertIn("no key and no secret", r.stdout.decode())

    def test_the_default_session_is_left_out_and_the_defaults_are_the_hostname_user_and_a_port(self):
        r = self.run_cli("--ssh-dir", self.ssh, "--no-qr")
        self.assertEqual(0, r.returncode, r.stderr)
        fields = parse_link(self.link_of(r.stdout))
        self.assertNotIn("session", fields)
        self.assertEqual(pp.default_host(), fields["host"])
        self.assertEqual(self.fp, fields["fp"])
        self.assertTrue(1 <= int(fields["port"]) <= 65535)

    def test_the_session_comes_from_the_socket_path_too(self):
        r = self.run_cli("--ssh-dir", self.ssh, "--no-qr", HERDR_SOCKET_PATH="/h/.config/herdr/sessions/paddock-test/herdr.sock")
        self.assertEqual("paddock-test", parse_link(self.link_of(r.stdout)).get("session"))

    def test_no_host_key_files_means_no_link(self):
        empty = tempfile.mkdtemp()
        try:
            r = self.run_cli("--ssh-dir", empty, "--no-qr")
            self.assertEqual(3, r.returncode)
            self.assertNotIn("paddock://", r.stdout.decode() + r.stderr.decode())
            self.assertIn("without a fingerprint is not made", r.stderr.decode())
        finally:
            shutil.rmtree(empty, ignore_errors=True)

    def test_a_bad_argument_makes_no_link(self):
        for args in (["--host", "a b"], ["--host", "a/b"], ["--port", "0"], ["--port", "70000"], ["--user", "a b"]):
            with self.subTest(args):
                r = self.run_cli(*(args + ["--ssh-dir", self.ssh, "--no-qr"]))
                self.assertEqual(2, r.returncode)
                self.assertNotIn("paddock://", r.stdout.decode())

    def test_an_invalid_session_name_is_dropped_with_a_note_not_put_in_the_link(self):
        r = self.run_cli("--ssh-dir", self.ssh, "--no-qr", HERDR_SESSION=".bad name")
        self.assertEqual(0, r.returncode)
        self.assertNotIn("session", parse_link(self.link_of(r.stdout)))
        self.assertIn("names no session", r.stdout.decode())

    def test_a_qr_is_drawn_only_when_qrencode_exists_and_never_by_adding_anything(self):
        bindir = tempfile.mkdtemp()
        try:
            fake = os.path.join(bindir, "qrencode")
            with open(fake, "w") as f:
                f.write("#!/bin/sh\necho QR-OF \"$5\"\n")
            os.chmod(fake, 0o755)
            path = bindir + os.pathsep + "/usr/bin" + os.pathsep + "/bin"
            r = self.run_cli("--ssh-dir", self.ssh, PATH=path)
            self.assertIn("QR-OF paddock://pair?", r.stdout.decode())
            r = self.run_cli("--ssh-dir", self.ssh, "--no-qr", PATH=path)
            self.assertNotIn("QR-OF", r.stdout.decode())
            os.remove(fake)
            r = self.run_cli("--ssh-dir", self.ssh, PATH=bindir)
            self.assertEqual(0, r.returncode)
            self.assertIn("paddock://pair?", r.stdout.decode())
        finally:
            shutil.rmtree(bindir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
