"""The pair popup: its library pieces one by one, then bin/pair.py run for real (a pipe with --stdin, and a pty for the terminal paths).

Nothing here touches the real camera, the real network address, ~/.ssh or herdr: `zbarcam`, `qrencode` and `ip` are fake scripts
on a temporary PATH that holds nothing else, the camera device is an ordinary temporary file, and every run writes to a temporary
HOME. The listener is only ever bound to 127.0.0.1.
"""
import base64
import io
import json
import os
import pty
import re
import select
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

from support import BIN, GOOD_BODY, GOOD_FINGERPRINT, GOOD_LINE, OTHER_LINE
from test_keys import HOSTILE, MARK, non_canonical_bodies
from test_pairing import FP, parse_link
import paddock_plugin as pp

PAIR = os.path.join(BIN, "pair.py")
V = "paddock-pair/1"


def completed(stdout=b"", code=0):
    return subprocess.CompletedProcess([], code, stdout, b"")


class NewSid(unittest.TestCase):
    def test_it_is_22_base64url_characters_and_never_repeats(self):
        seen = set()
        for _ in range(200):
            sid = pp.new_sid()
            self.assertRegex(sid, r"^[A-Za-z0-9_-]{22}\Z")
            seen.add(sid)
        self.assertEqual(200, len(seen))

    def test_it_comes_from_16_random_bytes(self):
        with mock.patch.object(pp.secrets, "token_urlsafe", return_value="A" * 22) as m:
            self.assertEqual("A" * 22, pp.new_sid())
        m.assert_called_once_with(16)

    def test_padding_is_stripped_and_a_wrong_length_is_an_error(self):
        with mock.patch.object(pp.secrets, "token_urlsafe", return_value="A" * 22 + "=="):
            self.assertEqual("A" * 22, pp.new_sid())
        with mock.patch.object(pp.secrets, "token_urlsafe", return_value="A" * 21):
            with self.assertRaises(AssertionError):
                pp.new_sid()


class BuildLinkPair(unittest.TestCase):
    SID = "abcDEF0123456789_-abcd"

    def test_the_old_form_is_byte_identical_without_both_new_parameters(self):
        old = "paddock://pair?v=1&host=box&port=22&user=alice&fp=%s" % FP
        self.assertEqual(old, pp.build_link("box", 22, "alice", [FP]))
        self.assertEqual(old, pp.build_link("box", 22, "alice", [FP], None, None, None))
        self.assertEqual(old, pp.build_link("box", 22, "alice", [FP], pair_port=4000), "a port alone adds nothing")
        self.assertEqual(old, pp.build_link("box", 22, "alice", [FP], sid=self.SID), "a handle alone adds nothing")
        self.assertEqual(old + "&session=work", pp.build_link("box", 22, "alice", [FP], "work"))

    def test_both_are_appended_last_in_this_order(self):
        link = pp.build_link("box", 22, "alice", [FP], "work", 41234, self.SID)
        self.assertEqual("paddock://pair?v=1&host=box&port=22&user=alice&fp=%s&session=work&pair=41234&sid=%s" % (FP, self.SID), link)
        fields = parse_link(link)
        self.assertEqual(["v", "host", "port", "user", "fp", "session", "pair", "sid"], list(fields))
        self.assertEqual("41234", fields["pair"])
        self.assertEqual(self.SID, fields["sid"])
        self.assertTrue(pp.build_link("box", 22, "alice", [FP], None, 1, self.SID).endswith("&pair=1&sid=" + self.SID))
        self.assertTrue(pp.build_link("box", 22, "alice", [FP], None, 65535, self.SID).endswith("&pair=65535&sid=" + self.SID))

    def test_a_port_or_handle_the_app_would_refuse_is_refused_here(self):
        for name, change in [
            ("port 0", dict(pair_port=0)), ("port 65536", dict(pair_port=65536)), ("a negative port", dict(pair_port=-1)),
            ("a string port", dict(pair_port="4000")), ("a float port", dict(pair_port=4000.0)), ("True as a port", dict(pair_port=True)),
            ("a short sid", dict(sid="A" * 21)), ("a long sid", dict(sid="A" * 23)), ("a sid with a plus", dict(sid="A" * 21 + "+")),
            ("a sid with padding", dict(sid="A" * 21 + "=")), ("a sid with a newline", dict(sid="A" * 22 + "\n")), ("an empty sid", dict(sid="")),
            ("a sid with a space", dict(sid="A" * 21 + " ")), ("a non-string sid", dict(sid=b"A" * 22)),
        ]:
            with self.subTest(name):
                args = dict(pair_port=4000, sid=self.SID)
                args.update(change)
                with self.assertRaises(pp.Refusal):
                    pp.build_link("box", 22, "alice", [FP], **args)


class CameraDevice(unittest.TestCase):
    def test_an_explicit_path_that_exists_is_used(self):
        with tempfile.NamedTemporaryFile() as f:
            self.assertEqual(f.name, pp.camera_device(f.name))

    def test_the_default_is_dev_video0_when_it_exists_else_none(self):
        with mock.patch.object(pp.os.path, "exists", side_effect=lambda p: p == "/dev/video0"):
            self.assertEqual("/dev/video0", pp.camera_device())
            self.assertEqual("/dev/video0", pp.camera_device(None))
            self.assertEqual("/dev/video0", pp.camera_device(""))
        with mock.patch.object(pp.os.path, "exists", return_value=False):
            self.assertIsNone(pp.camera_device())

    def test_a_named_device_that_is_missing_is_not_swapped_for_another_camera(self):
        with mock.patch.object(pp.os.path, "exists", side_effect=lambda p: p == "/dev/video0"):
            self.assertIsNone(pp.camera_device("/nonexistent/video9"))


class QrText(unittest.TestCase):
    def test_one_trailing_line_break_goes_and_nothing_else(self):
        for raw, want in [(b"abc\n", "abc"), (b"abc\r\n", "abc"), (b"abc", "abc"), (b"a\n\n", "a\n"), (b"a b \n", "a b "), (b"\n", None), (b"", None), (b"\r\n", None)]:
            with self.subTest(raw=raw):
                self.assertEqual(want, pp.qr_text(raw))

    def test_it_never_returns_more_than_the_cap(self):
        text = pp.qr_text(b"A" * 5000)
        self.assertEqual(pp.MAX_INPUT_BYTES + 2, len(text))
        with self.assertRaises(pp.Refusal):
            pp.parse_key_line(text)


class ReadQr(unittest.TestCase):
    def test_it_runs_zbarcam_with_the_documented_arguments_and_a_timeout(self):
        seen = {}

        def run(cmd, **kw):
            seen["cmd"], seen["kw"] = cmd, kw
            return completed((GOOD_LINE + "\n").encode())

        self.assertEqual(GOOD_LINE, pp.read_qr("/dev/video7", 12.5, run=run))
        self.assertEqual(["zbarcam", "--raw", "--oneshot", "--nodisplay", "--prescale=640x480", "/dev/video7"], seen["cmd"])
        self.assertEqual(12.5, seen["kw"]["timeout"])
        self.assertEqual(subprocess.DEVNULL, seen["kw"]["stdin"])
        self.assertEqual(subprocess.PIPE, seen["kw"]["stdout"])

    def test_none_for_every_way_it_can_fail_and_never_an_exception(self):
        def raising(exc):
            def run(cmd, **kw):
                raise exc
            return run

        for name, run in [
            ("a timeout", raising(subprocess.TimeoutExpired("zbarcam", 1))),
            ("no zbarcam on PATH", raising(FileNotFoundError(2, "No such file"))),
            ("not executable", raising(PermissionError(13, "denied"))),
            ("another subprocess error", raising(subprocess.SubprocessError("x"))),
            ("a non-zero exit", lambda cmd, **kw: completed(b"something\n", 1)),
            ("a signal exit", lambda cmd, **kw: completed(b"", -9)),
            ("no output", lambda cmd, **kw: completed(b"", 0)),
            ("only a newline", lambda cmd, **kw: completed(b"\n", 0)),
        ]:
            with self.subTest(name):
                self.assertIsNone(pp.read_qr("/dev/video0", 1, run=run))

    def test_the_output_is_cut_at_the_cap_and_a_text_stream_is_accepted(self):
        self.assertEqual(pp.MAX_INPUT_BYTES + 2, len(pp.read_qr("d", 1, run=lambda cmd, **kw: completed(b"B" * 4000))))
        self.assertEqual("abc", pp.read_qr("d", 1, run=lambda cmd, **kw: subprocess.CompletedProcess([], 0, "abc\n", "")))

    def test_against_a_real_fake_zbarcam_on_a_temporary_path(self):
        with FakeBin() as fb:
            fb.zbarcam(GOOD_LINE)
            with mock.patch.dict(os.environ, {"PATH": fb.dir}):
                self.assertEqual(GOOD_LINE, pp.read_qr("/dev/null", 5))
            fb.zbarcam(None, hang=True)
            started = time.time()
            with mock.patch.dict(os.environ, {"PATH": fb.dir}):
                self.assertIsNone(pp.read_qr("/dev/null", 0.5))
            self.assertLess(time.time() - started, 5)
            self.assertTrue(fb.gone(), "a timed-out zbarcam is killed")
            fb.zbarcam(None, code=1)
            with mock.patch.dict(os.environ, {"PATH": fb.dir}):
                self.assertIsNone(pp.read_qr("/dev/null", 5))
        with mock.patch.dict(os.environ, {"PATH": tempfile.gettempdir() + "/pdk-no-such-dir"}):
            self.assertIsNone(pp.read_qr("/dev/null", 1))


class DrawQr(unittest.TestCase):
    def test_the_code_is_drawn_with_a_light_border_of_two_modules(self):
        with FakeBin() as fb:
            rec = os.path.join(fb._tmp.name, "qr-args")
            fb.script("qrencode", "import sys\nopen(%r, 'w').write(' '.join(sys.argv[1:]))\nprint('QR')\n" % rec, python=True)
            with mock.patch.dict(os.environ, {"PATH": fb.dir}):
                self.assertEqual("QR\n", pp.draw_qr("paddock://pair?x"))
            with open(rec) as f:
                self.assertEqual("-t ANSIUTF8 -m 2 paddock://pair?x", f.read())


class CopyToClipboard(unittest.TestCase):
    def tool(self, fb, name, code=0):
        """A fake clipboard tool that writes what it was given to a file named after it, and exits with [code]."""
        out = os.path.join(fb._tmp.name, name + "-got")
        fb.script(name, "import sys\nopen(%r, 'w').write(sys.stdin.read() + '|' + ' '.join(sys.argv[1:]))\nsys.exit(%d)\n" % (out, code), python=True)
        return out

    def got(self, path):
        try:
            with open(path) as f:
                return f.read()
        except OSError:
            return None

    def test_wl_copy_gets_exactly_the_text_when_the_session_is_wayland(self):
        with FakeBin() as fb:
            out = self.tool(fb, "wl-copy")
            with mock.patch.dict(os.environ, {"PATH": fb.dir}):
                self.assertEqual("wl-copy", pp.copy_to_clipboard("paddock://pair?v=1", env={"WAYLAND_DISPLAY": "wayland-1"}))
            self.assertEqual("paddock://pair?v=1|", self.got(out))

    def test_xclip_and_xsel_are_used_on_an_x11_session_with_the_clipboard_selection(self):
        with FakeBin() as fb:
            xclip = self.tool(fb, "xclip")
            with mock.patch.dict(os.environ, {"PATH": fb.dir}):
                self.assertEqual("xclip", pp.copy_to_clipboard("L", env={"DISPLAY": ":0"}))
            self.assertEqual("L|-selection clipboard", self.got(xclip))
        with FakeBin() as fb:
            xsel = self.tool(fb, "xsel")
            with mock.patch.dict(os.environ, {"PATH": fb.dir}):
                self.assertEqual("xsel", pp.copy_to_clipboard("L", env={"DISPLAY": ":0"}))
            self.assertEqual("L|--clipboard --input", self.got(xsel))

    def test_a_tool_for_a_display_server_the_session_does_not_have_is_not_run(self):
        with FakeBin() as fb:
            wl = self.tool(fb, "wl-copy")
            with mock.patch.dict(os.environ, {"PATH": fb.dir}):
                self.assertIsNone(pp.copy_to_clipboard("L", env={"DISPLAY": ":0"}))
                self.assertIsNone(pp.copy_to_clipboard("L", env={}))
            self.assertIsNone(self.got(wl))

    def test_a_tool_that_fails_is_skipped_for_the_next_one(self):
        with FakeBin() as fb:
            self.tool(fb, "wl-copy", code=1)
            xclip = self.tool(fb, "xclip")
            with mock.patch.dict(os.environ, {"PATH": fb.dir}):
                self.assertEqual("xclip", pp.copy_to_clipboard("L", env={"WAYLAND_DISPLAY": "w", "DISPLAY": ":0"}))
            self.assertEqual("L|-selection clipboard", self.got(xclip))

    def test_no_tool_gives_none(self):
        with mock.patch.dict(os.environ, {"PATH": tempfile.gettempdir() + "/pdk-no-such-dir"}):
            self.assertIsNone(pp.copy_to_clipboard("L", env={"WAYLAND_DISPLAY": "w", "DISPLAY": ":0"}))

    def test_a_tool_that_hangs_is_given_up_on(self):
        def hang(cmd, **kw):
            raise subprocess.TimeoutExpired(cmd, 5)
        with FakeBin() as fb:
            self.tool(fb, "wl-copy")
            with mock.patch.dict(os.environ, {"PATH": fb.dir}):
                self.assertIsNone(pp.copy_to_clipboard("L", env={"WAYLAND_DISPLAY": "w"}, run=hang))

    def test_the_terminal_escape_carries_the_text_as_base64(self):
        self.assertEqual("\033]52;c;%s\a" % base64.b64encode(b"paddock://pair?v=1").decode(), pp.osc52_copy("paddock://pair?v=1"))


def ip_runner(addr_info=None, routes=None):
    """A stand-in for subprocess.run that answers `ip -json -4 route show default` and `ip -json -4 addr [show [dev X]]`."""
    routes = routes if routes is not None else [{"dst": "default", "dev": "wlan0", "metric": 600, "prefsrc": "192.168.42.86"}]
    addr_info = addr_info if addr_info is not None else [{"family": "inet", "local": "192.168.42.86", "prefixlen": 24, "scope": "global"}]

    def run(cmd, **kw):
        out = routes if "route" in cmd else [{"ifname": "wlan0", "addr_info": addr_info}]
        return subprocess.CompletedProcess(cmd, 0, json.dumps(out).encode(), b"")
    return run


class DefaultHost(unittest.TestCase):
    def test_it_is_the_lan_address_a_phone_can_use_not_the_host_name(self):
        self.assertEqual("192.168.42.86", pp.default_host(ip_runner()))

    def test_it_falls_back_to_the_host_name_only_without_a_lan_address(self):
        def no_ip(cmd, **kw):
            raise FileNotFoundError(2, "No such file")
        self.assertEqual(socket.gethostname(), pp.default_host(no_ip))
        self.assertEqual(socket.gethostname(), pp.default_host(ip_runner(routes=[])))


class LanNetwork(unittest.TestCase):
    def test_it_is_the_network_the_address_is_on(self):
        self.assertEqual("192.168.42.0/24", pp.lan_network("192.168.42.86", ip_runner()))
        self.assertEqual("10.0.0.0/16", pp.lan_network("10.0.3.4", ip_runner([{"family": "inet", "local": "10.0.3.4", "prefixlen": 16}])))

    def test_it_is_none_when_ip_does_not_say(self):
        self.assertIsNone(pp.lan_network("192.168.42.99", ip_runner()))
        self.assertIsNone(pp.lan_network("192.168.42.86", ip_runner([{"family": "inet", "local": "192.168.42.86"}])))
        self.assertIsNone(pp.lan_network("192.168.42.86", ip_runner([{"family": "inet", "local": "192.168.42.86", "prefixlen": "24"}])))

        def no_ip(cmd, **kw):
            raise FileNotFoundError(2, "No such file")
        self.assertIsNone(pp.lan_network("192.168.42.86", no_ip))


class FirewallNote(unittest.TestCase):
    @staticmethod
    def systemctl(active):
        def run(cmd, **kw):
            assert cmd[:3] == ["systemctl", "is-active", "--quiet"], cmd
            return subprocess.CompletedProcess(cmd, 0 if cmd[3] in active else 3)
        return run

    def test_an_active_ufw_gets_the_exact_commands_for_this_port_and_network(self):
        note = pp.firewall_note(45173, "192.168.42.0/24", self.systemctl({"ufw"}))
        self.assertIn("sudo ufw allow proto tcp from 192.168.42.0/24 to any port 45173\n", note)
        self.assertIn("sudo ufw delete allow proto tcp from 192.168.42.0/24 to any port 45173\n", note)

    def test_without_a_known_network_the_rule_names_no_source(self):
        note = pp.firewall_note(45173, None, self.systemctl({"ufw"}))
        self.assertIn("sudo ufw allow proto tcp to any port 45173\n", note)
        self.assertNotIn(" from ", note.split("sudo ufw allow")[1].split("\n")[0])

    def test_an_active_firewalld_gets_a_rule_that_lasts_until_the_next_reload(self):
        note = pp.firewall_note(45173, "192.168.42.0/24", self.systemctl({"firewalld"}))
        self.assertIn("sudo firewall-cmd --add-port=45173/tcp\n", note)
        self.assertIn("sudo firewall-cmd --remove-port=45173/tcp\n", note)
        self.assertNotIn("--permanent", note)

    def test_no_active_firewall_or_no_systemctl_says_nothing(self):
        self.assertIsNone(pp.firewall_note(45173, None, self.systemctl(set())))

        def none(cmd, **kw):
            raise FileNotFoundError(2, "No such file")

        def hangs(cmd, **kw):
            raise subprocess.TimeoutExpired(cmd, 5)
        self.assertIsNone(pp.firewall_note(45173, None, none))
        self.assertIsNone(pp.firewall_note(45173, None, hangs))

    def test_nothing_that_changes_a_firewall_is_ever_run(self):
        seen = []

        def run(cmd, **kw):
            seen.append(cmd)
            return subprocess.CompletedProcess(cmd, 0)
        pp.firewall_note(45173, "10.0.0.0/8", run)
        self.assertEqual([["systemctl", "is-active", "--quiet", "ufw"]], seen)


class ApprovePrompt(unittest.TestCase):
    def ask(self, typed, stream="text"):
        out = io.StringIO()
        if stream == "text":
            stdin = io.StringIO(typed)
        elif stream == "bytes":
            stdin = io.BytesIO(typed.encode())
        else:
            class Tty(object):  # like sys.stdin: a text stream whose bytes are on .buffer
                buffer = io.BytesIO(typed.encode())
            stdin = Tty()
        return pp.approve_prompt(GOOD_FINGERPRINT, stdin, out), out.getvalue()

    def test_only_an_explicit_a_and_enter_approves(self):
        for typed in ("a\n", "A\n", "a\r\n", "A\r\n"):
            for stream in ("text", "bytes", "buffer"):
                with self.subTest(typed=typed, stream=stream):
                    self.assertTrue(self.ask(typed, stream)[0])

    def test_everything_else_is_reject(self):
        for typed in ("", "\n", "\r\n", "R\n", "r\n", "reject\n", "x\n", "aa\n", "ab\n", " a\n", "a \n", "approve\n", "Approve\n", "y\n", "yes\n", "1\n",
                      "a", "A", "\na\n", "n\n", "a" * 100 + "\n", "\x1ba\n", "\xe1\n"):
            for stream in ("text", "bytes", "buffer"):
                with self.subTest(typed=typed, stream=stream):
                    self.assertFalse(self.ask(typed, stream)[0])

    def test_a_closed_or_failing_input_is_reject(self):
        class Broken(object):
            def readline(self, n=-1):
                raise OSError(5, "I/O error")

        self.assertFalse(pp.approve_prompt(GOOD_FINGERPRINT, Broken(), io.StringIO()))
        self.assertFalse(pp.approve_prompt(GOOD_FINGERPRINT, io.StringIO(""), io.StringIO()))

    def test_the_text_shows_the_full_fingerprint_and_sets_off_the_first_eight(self):
        _, text = self.ask("\n")
        self.assertIn(GOOD_FINGERPRINT, text, "the whole fingerprint, in one piece")
        self.assertIn("[StLaLXC/]", text)
        self.assertEqual("StLaLXC/", GOOD_FINGERPRINT[7:15])
        self.assertIn("Approve only if the phone shows the same fingerprint", text)
        self.assertNotIn(GOOD_BODY, text)
        text.encode("ascii")  # plain ASCII: it reads the same without colour
        self.assertNotIn("\x1b", text)

    def test_reject_is_listed_first_and_marked_as_the_default(self):
        _, text = self.ask("\n")
        self.assertIn("[R]eject (default) / [a]pprove", text)
        self.assertLess(text.index("[R]eject"), text.index("[a]pprove"))
        self.assertTrue(text.rstrip(" ").endswith(":") or text.endswith(": "))

    def test_the_fingerprint_head_of_other_shapes(self):
        self.assertEqual("StLaLXC/", pp.fingerprint_head(GOOD_FINGERPRINT))
        self.assertEqual("abcdefgh", pp.fingerprint_head("abcdefghijkl"))


class LanAddress(unittest.TestCase):
    def runner(self, route=None, addr=None, calls=None):
        def run(cmd, **kw):
            if calls is not None:
                calls.append(cmd)
            if cmd[:5] == ["ip", "-json", "-4", "route", "show"]:
                out = route
            elif cmd[:5] == ["ip", "-json", "-4", "addr", "show"]:
                out = addr
            else:
                raise AssertionError(cmd)
            if isinstance(out, Exception):
                raise out
            return completed(json.dumps(out).encode() if not isinstance(out, bytes) else out)
        return run

    def info(self, *addrs):
        return [{"ifname": "x", "addr_info": [{"family": "inet", "local": a, "scope": s} for a, s in addrs]}]

    def test_the_default_routes_device_and_its_address_with_the_exact_commands(self):
        calls = []
        run = self.runner([{"dst": "default", "gateway": "192.168.1.1", "dev": "wlan0", "metric": 600}], self.info(("192.168.1.20", "global")), calls)
        self.assertEqual("192.168.1.20", pp.lan_address(run))
        self.assertEqual([["ip", "-json", "-4", "route", "show", "default"], ["ip", "-json", "-4", "addr", "show", "dev", "wlan0"]], calls)

    def test_the_lowest_metric_route_wins_and_the_first_of_equals(self):
        calls = []
        run = self.runner([{"dev": "wlan0", "metric": 600}, {"dev": "eth0", "metric": 100}, {"dev": "eth1", "metric": 100}], self.info(("10.0.0.5", "global")), calls)
        pp.lan_address(run)
        self.assertEqual(["dev", "eth0"], calls[1][-2:])

    def test_a_route_without_a_metric_counts_as_zero(self):
        calls = []
        pp.lan_address(self.runner([{"dev": "wlan0", "metric": 600}, {"dev": "eth0"}], self.info(("10.0.0.5", "global")), calls))
        self.assertEqual(["dev", "eth0"], calls[1][-2:])

    def test_with_several_addresses_the_routes_preferred_source_then_a_global_one(self):
        addrs = self.info(("169.254.9.9", "link"), ("10.0.0.7", "global"), ("10.0.0.8", "global"))
        self.assertEqual("10.0.0.8", pp.lan_address(self.runner([{"dev": "e0", "prefsrc": "10.0.0.8"}], addrs)))
        self.assertEqual("10.0.0.7", pp.lan_address(self.runner([{"dev": "e0"}], addrs)))
        self.assertEqual("10.0.0.7", pp.lan_address(self.runner([{"dev": "e0", "prefsrc": "10.9.9.9"}], addrs)))
        self.assertEqual("169.254.9.9", pp.lan_address(self.runner([{"dev": "e0"}], self.info(("169.254.9.9", "link")))))

    def test_none_when_nothing_usable_is_found(self):
        ok = [{"dev": "e0"}]
        for name, route, addr in [
            ("no default route", [], self.info(("10.0.0.5", "global"))),
            ("no addresses on the device", ok, [{"ifname": "e0", "addr_info": []}]),
            ("an empty answer for the device", ok, []),
            ("only the unspecified address", ok, self.info(("0.0.0.0", "global"))),
            ("garbage in an address", ok, self.info(("not-an-address", "global"))),
            ("an IPv6 entry", ok, [{"addr_info": [{"family": "inet6", "local": "fe80::1", "scope": "link"}]}]),
            ("a route without a device", [{"dst": "default"}], self.info(("10.0.0.5", "global"))),
            ("a device name that is an option", [{"dev": "-x"}], self.info(("10.0.0.5", "global"))),
            ("a device name with a space", [{"dev": "a b"}], self.info(("10.0.0.5", "global"))),
            ("a device name of 16 characters", [{"dev": "a" * 16}], self.info(("10.0.0.5", "global"))),
            ("JSON that is not a list", {"dev": "e0"}, self.info(("10.0.0.5", "global"))),
            ("not JSON at all", b"not json", self.info(("10.0.0.5", "global"))),
            ("ip is missing", FileNotFoundError(2, "no ip"), None),
            ("ip is not executable", PermissionError(13, "no"), None),
            ("ip times out", subprocess.TimeoutExpired("ip", 5), None),
        ]:
            with self.subTest(name):
                self.assertIsNone(pp.lan_address(self.runner(route, addr)))

    def test_a_failing_ip_is_none(self):
        self.assertIsNone(pp.lan_address(lambda cmd, **kw: completed(b"[]", 1)))

    def test_the_real_ip_command_answers_with_an_address_or_nothing(self):
        if not shutil.which("ip"):
            self.skipTest("ip is not installed")
        got = pp.lan_address()
        self.assertTrue(got is None or re.match(r"^\d{1,3}(\.\d{1,3}){3}\Z", got), got)


# ---- bin/pair.py, run for real -----------------------------------------------------------------------------------------------------

class FakeBin(object):
    """A temporary PATH directory holding fake `zbarcam`, `qrencode` and `ip`, and nothing else (so the real ones are never reached)."""

    def __init__(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = os.path.join(self._tmp.name, "bin")
        os.mkdir(self.dir)
        self.marker = os.path.join(self._tmp.name, "zbarcam-ran")
        self.pidfile = os.path.join(self._tmp.name, "zbarcam-pid")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.cleanup()

    def cleanup(self):
        pid = self.pid()
        if pid:
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
        self._tmp.cleanup()

    def script(self, name, body, python=False):
        path = os.path.join(self.dir, name)
        with open(path, "w") as f:
            f.write(("#!%s\n" % sys.executable if python else "#!/bin/sh\n") + body)
        os.chmod(path, 0o755)

    def zbarcam(self, line, hang=False, code=0, delay=0.0):
        """Records its arguments and its pid; after [delay] seconds prints [line] (if any), or hangs until killed, or exits with [code]."""
        self.script("zbarcam", "import os, sys, time\n"
                    "open(%r, 'a').write(' '.join(sys.argv[1:]) + '\\n')\n"
                    "open(%r, 'w').write(str(os.getpid()))\n"
                    "time.sleep(%r)\n"
                    "if %r:\n    time.sleep(60)\n"
                    "if %r:\n    sys.stdout.write(%r + '\\n')\n    sys.stdout.flush()\n"
                    "sys.exit(%d)\n" % (self.marker, self.pidfile, delay, hang, line is not None, line, code), python=True)

    def qrencode(self):
        self.script("qrencode", 'echo QR-OF "$5"\n')

    def ip(self, address):
        self.script("ip", 'case "$*" in\n'
                    '  *route*) echo \'[{"dst":"default","dev":"dummy0","metric":100}]\' ;;\n'
                    '  *addr*) echo \'[{"ifname":"dummy0","addr_info":[{"family":"inet","local":"%s","scope":"global"}]}]\' ;;\nesac\n' % address)

    def ran(self):
        """The argument lines zbarcam was started with, one per start."""
        try:
            with open(self.marker) as f:
                return f.read().splitlines()
        except OSError:
            return []

    def pid(self):
        try:
            with open(self.pidfile) as f:
                return int(f.read())
        except (OSError, ValueError):
            return None

    def gone(self, wait=3.0):
        """True when the zbarcam that was started is no longer running."""
        pid = self.pid()
        end = time.time() + wait
        while pid and time.time() < end:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return True
            time.sleep(0.05)
        return pid is None or not _alive(pid)


def _alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def reference_bytes(line, seed=None):
    """What authorize() itself makes of [line] in a fresh temporary HOME (holding [seed] as authorized_keys first)."""
    with tempfile.TemporaryDirectory() as d:
        if seed is not None:
            os.mkdir(os.path.join(d, ".ssh"), 0o700)
            with open(os.path.join(d, ".ssh", "authorized_keys"), "wb") as f:
                f.write(seed)
            os.chmod(os.path.join(d, ".ssh", "authorized_keys"), 0o600)
        pp.authorize(d, pp.parse_key_line(line))
        with open(os.path.join(d, ".ssh", "authorized_keys"), "rb") as f:
            return f.read()


@unittest.skipUnless(shutil.which("ssh-keygen"), "ssh-keygen not installed")
class PairCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ssh = tempfile.mkdtemp()
        subprocess.check_call(["ssh-keygen", "-q", "-N", "", "-C", "t@h", "-t", "ed25519", "-f", os.path.join(cls.ssh, "ssh_host_ed25519_key")])
        cls.fp = subprocess.check_output(["ssh-keygen", "-lf", os.path.join(cls.ssh, "ssh_host_ed25519_key.pub")]).decode().split()[1]
        cls.base_link = "paddock://pair?v=1&host=box&port=22&user=alice&fp=" + cls.fp

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.ssh, ignore_errors=True)

    def setUp(self):
        self.fb = FakeBin()
        self.addCleanup(self.fb.cleanup)
        self._home = tempfile.TemporaryDirectory()
        self.addCleanup(self._home.cleanup)
        self.home = self._home.name
        self.camera = os.path.join(self.home, "video-test-device")  # an ordinary file: the camera is never opened, only named
        open(self.camera, "w").close()
        self.ak = os.path.join(self.home, ".ssh", "authorized_keys")

    def args(self, *extra):
        return ["--ssh-dir", self.ssh, "--home", self.home, "--host", "box", "--port", "22", "--user", "alice"] + list(extra)

    def env(self, **more):
        e = {"PATH": self.fb.dir, "HOME": self.home}
        e.update(more)
        return e

    def written(self):
        try:
            with open(self.ak, "rb") as f:
                return f.read()
        except OSError:
            return None

    def link_in(self, text):
        links = [l for l in text.splitlines() if l.startswith("paddock://")]
        self.assertEqual(1, len(links), text)
        return links[0]


class PairStdin(PairCase):
    def run_pair(self, stdin, *extra, **env):
        r = subprocess.run([sys.executable, PAIR, "--stdin"] + self.args(*extra), input=stdin if isinstance(stdin, bytes) else stdin.encode(),
                           env=self.env(**env), stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
        return r, r.stdout.decode("utf-8", "replace"), r.stderr.decode("utf-8", "replace")

    def assert_no_key_material(self, *texts):
        for t in texts:
            self.assertNotIn(GOOD_BODY, t)
            self.assertNotIn(GOOD_BODY[:30], t)
            self.assertNotIn("paddock@phone", t)
            self.assertNotIn("ecdsa-sha2-nistp256 AAAA", t, "no key line is ever printed")
            self.assertNotIn(MARK, t)

    # -- paste, approve, reject --------------------------------------------------------------------------------------------------

    def test_a_pasted_key_approved_with_a_writes_exactly_what_authorize_writes(self):
        r, out, err = self.run_pair(GOOD_LINE + "\na\n", "--no-listen", "--no-camera")
        self.assertEqual(0, r.returncode, err)
        self.assertEqual(reference_bytes(GOOD_LINE), self.written())
        self.assertEqual((GOOD_LINE + "\n").encode(), self.written())
        self.assertIn(GOOD_FINGERPRINT, out)
        self.assertIn(self.ak, out)
        self.assertIn("Now press Connect on the phone", out)
        self.assertEqual(0o600, os.stat(self.ak).st_mode & 0o777)
        self.assertEqual(0o700, os.stat(os.path.dirname(self.ak)).st_mode & 0o777)
        self.assert_no_key_material(out, err)

    def clipboard_got(self):
        try:
            with open(os.path.join(self.fb._tmp.name, "clip")) as f:
                return f.read()
        except OSError:
            return None

    def fake_wl_copy(self):
        self.fb.script("wl-copy", "import sys\nopen(%r, 'w').write(sys.stdin.read())\n" % os.path.join(self.fb._tmp.name, "clip"), python=True)

    def test_c_copies_exactly_the_pairing_link_and_the_run_goes_on_to_approve_the_key(self):
        self.fake_wl_copy()
        r, out, err = self.run_pair("c\n" + GOOD_LINE + "\na\n", "--no-listen", "--no-camera", WAYLAND_DISPLAY="wayland-test")
        self.assertEqual(0, r.returncode, err)
        self.assertEqual(self.link_in(out), self.clipboard_got(), "the clipboard holds the link and nothing else")
        self.assertIn("Copied the pairing link to the clipboard (wl-copy)", out)
        self.assertEqual(reference_bytes(GOOD_LINE), self.written(), "the key after the copy was approved as usual")
        self.assert_no_key_material(out, err)

    def test_copy_in_any_case_and_with_a_carriage_return_does_the_same(self):
        self.fake_wl_copy()
        for typed in ("copy\n", "C\r\n", " c \n"):
            with self.subTest(typed=typed):
                if os.path.exists(os.path.join(self.fb._tmp.name, "clip")):
                    os.remove(os.path.join(self.fb._tmp.name, "clip"))
                r, out, err = self.run_pair(typed + "\n", "--no-listen", "--no-camera", WAYLAND_DISPLAY="wayland-test")
                self.assertEqual(self.link_in(out), self.clipboard_got())
                self.assertEqual(1, r.returncode, "no key came: that ends as it always did")
                self.assertNotIn("Refused", out + err, "a copy is not a refused paste")

    def test_c_with_no_clipboard_tool_says_so_and_does_not_end_the_run(self):
        r, out, err = self.run_pair("c\n" + GOOD_LINE + "\na\n", "--no-listen", "--no-camera")
        self.assertEqual(0, r.returncode, err)
        self.assertIn("not copied", out)
        self.assertEqual(reference_bytes(GOOD_LINE), self.written())

    def test_c_at_the_approval_prompt_is_a_reject_not_a_copy(self):
        self.fake_wl_copy()
        r, out, err = self.run_pair(GOOD_LINE + "\nc\n", "--no-listen", "--no-camera", WAYLAND_DISPLAY="wayland-test")
        self.assertEqual(1, r.returncode, err)
        self.assertIsNone(self.written())
        self.assertIsNone(self.clipboard_got(), "only the wait for the key takes the command")

    def test_an_uppercase_A_and_crlf_approve_too(self):
        for typed in ("A\n", "a\r\n"):
            with self.subTest(typed=typed):
                shutil.rmtree(os.path.join(self.home, ".ssh"), ignore_errors=True)
                r, out, err = self.run_pair(GOOD_LINE + "\n" + typed, "--no-listen", "--no-camera")
                self.assertEqual(0, r.returncode, err)
                self.assertEqual(reference_bytes(GOOD_LINE), self.written())

    def test_an_existing_authorized_keys_is_extended_exactly_as_authorize_extends_it(self):
        seed = b"# mine\nssh-ed25519 AAAAC3Nza-other someone@laptop"  # no trailing newline
        os.mkdir(os.path.dirname(self.ak), 0o700)
        with open(self.ak, "wb") as f:
            f.write(seed)
        os.chmod(self.ak, 0o600)
        r, out, err = self.run_pair(GOOD_LINE + "\na\n", "--no-listen", "--no-camera")
        self.assertEqual(0, r.returncode, err)
        self.assertEqual(reference_bytes(GOOD_LINE, seed), self.written())
        self.assertTrue(self.written().startswith(seed))

    def test_a_key_that_is_already_authorized_is_said_so_and_the_file_is_unchanged(self):
        self.run_pair(GOOD_LINE + "\na\n", "--no-listen", "--no-camera")
        before = self.written()
        r, out, err = self.run_pair(GOOD_LINE + "\na\n", "--no-listen", "--no-camera")
        self.assertEqual(0, r.returncode, err)
        self.assertIn("already authorized", out)
        self.assertEqual(before, self.written())

    def test_reject_is_the_default_and_writes_nothing(self):
        for name, stdin in [
            ("an empty line", GOOD_LINE + "\n\n"), ("R", GOOD_LINE + "\nR\n"), ("r", GOOD_LINE + "\nr\n"), ("end of input", GOOD_LINE + "\n"),
            ("end of input without a line end on the key", GOOD_LINE), ("no", GOOD_LINE + "\nno\n"), ("aa", GOOD_LINE + "\naa\n"),
            ("approve", GOOD_LINE + "\napprove\n"), ("a without Enter", GOOD_LINE + "\na"), ("a space and a", GOOD_LINE + "\n a\n"),
            ("y", GOOD_LINE + "\ny\n"), ("another key line", GOOD_LINE + "\n" + OTHER_LINE + "\n"),
        ]:
            with self.subTest(name):
                r, out, err = self.run_pair(stdin, "--no-listen", "--no-camera")
                self.assertEqual(1, r.returncode, err)
                self.assertIsNone(self.written(), "something was written")
                self.assertFalse(os.path.exists(os.path.join(self.home, ".ssh")), "even the directory was created")
                self.assertIn("Rejected", out + err)
                self.assertIn("Nothing was written", out + err)
                self.assertIn(GOOD_FINGERPRINT, out)
                self.assert_no_key_material(out, err)

    def test_blank_lines_before_the_key_are_just_enters_and_are_ignored(self):
        r, out, err = self.run_pair("\n\n" + GOOD_LINE + "\na\n", "--no-listen", "--no-camera")
        self.assertEqual(0, r.returncode, err)
        self.assertEqual(reference_bytes(GOOD_LINE), self.written())

    def test_without_any_key_the_run_ends_at_once_and_says_nothing_can_arrive(self):
        started = time.time()
        r, out, err = self.run_pair("", "--no-listen", "--no-camera")
        self.assertEqual(1, r.returncode)
        self.assertLess(time.time() - started, 10, "it must not wait out the 120 seconds")
        self.assertIn("nothing can arrive", err)
        self.assertIsNone(self.written())

    # -- refusals ----------------------------------------------------------------------------------------------------------------

    def test_every_line_the_key_check_refuses_ends_the_run_with_the_reason_and_writes_nothing(self):
        tried = 0
        for name, data, fragment in HOSTILE:
            body = data[:-1] if data.endswith("\n") else data
            if "\n" in body or not body.strip("\n"):
                continue  # more than one line, or a blank line: the first line decides here, and a blank line is an Enter
            tried += 1
            with self.subTest(name):
                r, out, err = self.run_pair(data.encode("utf-8", "surrogateescape"), "--no-listen", "--no-camera")
                self.assertEqual(2, r.returncode)
                self.assertIn(fragment, out + err)
                self.assertIn("Refused", out + err)
                self.assertFalse(os.path.exists(os.path.join(self.home, ".ssh")))
                self.assertNotIn(MARK, out + err)
                self.assertNotIn(GOOD_BODY[:30], out + err)
        self.assertGreater(tried, 35)

    def test_the_popup_and_authorize_phone_accept_exactly_the_same_spellings_of_a_key(self):
        # the canonical body and the three spellings that decode to the same blob: the one rule, applied by both programs
        seen = {}
        for body in [GOOD_BODY] + non_canonical_bodies():
            line = "ecdsa-sha2-nistp256 " + body + " paddock@phone\n"
            r, out, err = self.run_pair(line + "a\n", "--no-listen", "--no-camera")
            popup = (r.returncode, self.written())
            shutil.rmtree(os.path.join(self.home, ".ssh"), ignore_errors=True)
            a = subprocess.run([sys.executable, os.path.join(BIN, "authorize_phone.py"), "--stdin", "--home", self.home], input=line.encode(),
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20)
            authorize = (a.returncode, self.written())
            shutil.rmtree(os.path.join(self.home, ".ssh"), ignore_errors=True)
            with self.subTest(body=body[-4:]):
                self.assertEqual(authorize, popup)
                self.assertNotIn(body, out + err + a.stdout.decode() + a.stderr.decode())
            seen[body] = popup[0]
        self.assertEqual(0, seen[GOOD_BODY])
        self.assertEqual([2, 2, 2], [seen[b] for b in non_canonical_bodies()])

    def test_a_private_key_header_is_refused_without_being_shown(self):
        header = "-----BEG" + "IN OPENSSH PRIV" + "ATE KEY-----" + MARK  # assembled so this file never holds the literal marker
        r, out, err = self.run_pair(header + "\n", "--no-listen", "--no-camera")
        self.assertEqual(2, r.returncode)
        self.assertIn("looks like a private key", out + err)
        self.assertNotIn(MARK, out + err)
        self.assertNotIn("OPENSSH", out + err)
        self.assertIsNone(self.written())

    def test_a_write_the_file_system_refuses_is_reported_and_exits_with_authorizes_code(self):
        target = os.path.join(self.home, "t")
        os.mkdir(target)
        os.symlink(target, os.path.join(self.home, ".ssh"))
        r, out, err = self.run_pair(GOOD_LINE + "\na\n", "--no-listen", "--no-camera")
        self.assertEqual(3, r.returncode)
        self.assertIn("symbolic link", out + err)
        self.assertIn("not written", out + err)
        self.assertNotIn("Now press Connect", out)
        self.assertEqual([], os.listdir(target))

    # -- the link and the QR -----------------------------------------------------------------------------------------------------

    def test_the_link_is_the_one_show_pairing_makes_when_nothing_listens(self):
        r, out, err = self.run_pair(GOOD_LINE + "\n", "--no-listen", "--no-camera", "--no-qr", HERDR_SESSION="work")
        self.assertEqual(self.base_link + "&session=work", self.link_in(out))
        r, out, err = self.run_pair(GOOD_LINE + "\n", "--no-listen", "--no-camera", "--no-qr")
        self.assertEqual(self.base_link, self.link_in(out))
        self.assertNotIn("sid", out.replace("considered", ""))
        # and the same link, field for field, as the show-pairing program prints
        show = subprocess.run([sys.executable, os.path.join(BIN, "show_pairing.py"), "--no-prompt", "--no-qr", "--ssh-dir", self.ssh, "--host", "box",
                               "--port", "22", "--user", "alice"], env=self.env(), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(self.base_link, self.link_in(show.stdout.decode()))

    def test_a_stdin_run_opens_no_listener_unless_it_is_told_where(self):
        r, out, err = self.run_pair(GOOD_LINE + "\n", "--no-qr", "--no-camera")
        self.assertEqual(self.base_link, self.link_in(out))
        self.assertIn("listener: off", out)
        self.assertNotIn("listening on", out)

    def test_with_a_listener_the_link_carries_its_port_and_a_fresh_sid(self):
        links = []
        for _ in range(2):
            r, out, err = self.run_pair(GOOD_LINE + "\n", "--listen-ip", "127.0.0.1", "--no-camera", "--no-qr")
            link = self.link_in(out)
            fields = parse_link(link)
            m = re.search(r"listening on 127\.0\.0\.1:(\d+) for the phone", out)
            self.assertTrue(m, out)
            self.assertEqual(m.group(1), fields["pair"])
            self.assertRegex(fields["sid"], r"^[A-Za-z0-9_-]{22}\Z")
            self.assertTrue(link.startswith(self.base_link + "&pair="))
            links.append(link)
        self.assertNotEqual(parse_link(links[0])["sid"], parse_link(links[1])["sid"])

    def test_the_popup_says_when_the_links_host_is_not_the_listeners_address(self):
        r, out, err = self.run_pair(GOOD_LINE + "\n", "--listen-ip", "127.0.0.1", "--no-camera", "--no-qr")
        self.assertIn("the phone connects to the link's host (box) at that port, so that name must reach 127.0.0.1", out)
        self.assertIn("run again with --host 127.0.0.1", out)
        r, out, err = self.run_pair(GOOD_LINE + "\n", "--listen-ip", "127.0.0.1", "--no-camera", "--no-qr", "--host", "127.0.0.1")
        self.assertIn("listening on 127.0.0.1:", out)
        self.assertNotIn("must reach", out)

    def test_a_listener_address_that_is_public_or_wild_is_refused_and_the_link_is_the_plain_one(self):
        for ip in ("8.8.8.8", "0.0.0.0", "224.0.0.1", "not-an-ip"):
            with self.subTest(ip):
                r, out, err = self.run_pair(GOOD_LINE + "\n", "--listen-ip", ip, "--no-camera", "--no-qr")
                self.assertEqual(self.base_link, self.link_in(out))
                self.assertIn("listener: off", out)
                self.assertNotIn("listening on", out)

    def test_a_bad_host_port_or_user_stops_before_any_socket_is_opened(self):
        for args in (["--host", "a b"], ["--host", "a/b"], ["--port", "0"], ["--port", "70000"], ["--user", "a b"]):
            with self.subTest(args):
                cmd = [sys.executable, PAIR, "--stdin", "--ssh-dir", self.ssh, "--home", self.home, "--host", "box", "--port", "22", "--user", "alice"]
                cmd += ["--listen-ip", "127.0.0.1", "--no-camera"]
                for i in range(0, len(args), 2):
                    cmd[cmd.index(args[i]) + 1] = args[i + 1]
                r = subprocess.run(cmd, input=GOOD_LINE.encode() + b"\na\n", env=self.env(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
                self.assertEqual(2, r.returncode)
                self.assertNotIn(b"paddock://", r.stdout)
                self.assertNotIn(b"listening on", r.stdout)
                self.assertIsNone(self.written())

    def test_no_host_key_files_means_no_link_and_no_listener(self):
        empty = tempfile.mkdtemp()
        try:
            r = subprocess.run([sys.executable, PAIR, "--stdin", "--ssh-dir", empty, "--home", self.home, "--listen-ip", "127.0.0.1"], input=GOOD_LINE.encode(),
                               env=self.env(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
            self.assertEqual(3, r.returncode)
            self.assertNotIn(b"paddock://", r.stdout + r.stderr)
            self.assertNotIn(b"listening on", r.stdout)
            self.assertIn(b"without a fingerprint is not made", r.stderr)
        finally:
            shutil.rmtree(empty, ignore_errors=True)

    def test_the_qr_is_drawn_only_when_qrencode_exists_and_no_qr_is_absent(self):
        self.fb.qrencode()
        r, out, err = self.run_pair(GOOD_LINE + "\n", "--no-listen", "--no-camera")
        self.assertIn("QR-OF " + self.base_link, out)
        r, out, err = self.run_pair(GOOD_LINE + "\n", "--no-listen", "--no-camera", "--no-qr")
        self.assertNotIn("QR-OF", out)
        self.assertNotIn("No QR code", out)
        os.remove(os.path.join(self.fb.dir, "qrencode"))
        r, out, err = self.run_pair(GOOD_LINE + "\n", "--no-listen", "--no-camera")
        self.assertEqual(self.base_link, self.link_in(out))
        self.assertNotIn("QR-OF", out)
        self.assertIn("No QR code is drawn", out)

    def test_the_qr_is_of_the_link_with_pair_and_sid_when_listening(self):
        self.fb.qrencode()
        r, out, err = self.run_pair(GOOD_LINE + "\n", "--listen-ip", "127.0.0.1", "--no-camera")
        link = self.link_in(out)
        self.assertIn("&pair=", link)
        self.assertIn("QR-OF " + link, out)

    # -- the camera --------------------------------------------------------------------------------------------------------------

    def test_the_camera_is_not_started_before_enter_or_without_camera_now(self):
        self.fb.zbarcam(GOOD_LINE)
        r, out, err = self.run_pair(GOOD_LINE + "\n\n", "--no-listen", "--camera-device", self.camera)
        self.assertEqual([], self.fb.ran(), "zbarcam must not run in a --stdin run unless --camera-now says so")
        self.assertIn("camera %s ready" % self.camera, out)
        self.assertNotIn("Camera on", out)

    def test_camera_now_starts_it_at_once_and_a_good_code_goes_to_the_prompt(self):
        self.fb.zbarcam(GOOD_LINE)
        r, out, err = self.run_pair("", "--no-listen", "--camera-now", "--camera-device", self.camera)
        self.assertEqual(["--raw --oneshot --nodisplay --prescale=640x480 " + self.camera], self.fb.ran())
        self.assertIn("A key arrived from the camera", out)
        self.assertIn(GOOD_FINGERPRINT, out)
        self.assertIn("camera %s on now" % self.camera, out)
        self.assertEqual(1, r.returncode, "no answer on standard input is a reject")
        self.assertIsNone(self.written())
        self.assertTrue(self.fb.gone())
        self.assert_no_key_material(out, err)

    def test_junk_from_the_camera_is_refused_without_being_shown(self):
        self.fb.zbarcam("https://example.org/" + MARK)
        r, out, err = self.run_pair("", "--no-listen", "--camera-now", "--camera-device", self.camera)
        self.assertEqual(2, r.returncode)
        self.assertIn("Refused (the camera)", out + err)
        self.assertNotIn(MARK, out + err)
        self.assertNotIn("example.org", out + err)
        self.assertIsNone(self.written())
        self.assertFalse(os.path.exists(os.path.join(self.home, ".ssh")))

    def test_a_camera_that_reads_nothing_times_out_and_is_killed(self):
        self.fb.zbarcam(None, hang=True)
        started = time.time()
        r, out, err = self.run_pair("", "--no-listen", "--camera-now", "--camera-device", self.camera, "--timeout", "1")
        self.assertLess(time.time() - started, 15)
        self.assertEqual(1, r.returncode)
        self.assertIn("No key arrived within 1 seconds", out + err)
        self.assertTrue(self.fb.gone(), "zbarcam is still running after the popup ended")
        self.assertIn("Camera off", out)
        self.assertIsNone(self.written())

    def test_a_camera_that_fails_is_reported_and_the_other_intakes_go_on(self):
        self.fb.zbarcam(None, code=1)
        r, out, err = self.run_pair("", "--no-listen", "--camera-now", "--camera-device", self.camera)
        self.assertIn("zbarcam exited with status 1", out)
        self.assertIn("no key was read", out)
        self.assertEqual(1, r.returncode)
        self.fb.zbarcam(None, code=0)
        r, out, err = self.run_pair("", "--no-listen", "--camera-now", "--camera-device", self.camera)
        self.assertIn("no code was read", out)

    def test_when_the_paste_wins_the_camera_is_never_the_one_that_answers(self):
        self.fb.zbarcam(GOOD_LINE.replace("paddock@phone", "camera@phone"), delay=0.5)
        r, out, err = self.run_pair(GOOD_LINE + "\na\n", "--no-listen", "--camera-now", "--camera-device", self.camera)
        self.assertEqual(0, r.returncode, err)
        self.assertEqual((GOOD_LINE + "\n").encode(), self.written())
        self.assertIn("a pasted line", out)

    def test_no_camera_and_a_missing_device_and_a_missing_zbarcam_are_each_said_and_paste_stays(self):
        self.fb.zbarcam(GOOD_LINE)
        r, out, err = self.run_pair(GOOD_LINE + "\n", "--no-listen", "--no-camera", "--camera-device", self.camera)
        self.assertIn("camera: off (--no-camera)", out)
        self.assertEqual(1, r.returncode)
        self.assertIn("A key arrived from a pasted line", out)
        r, out, err = self.run_pair(GOOD_LINE + "\na\n", "--no-listen", "--camera-device", os.path.join(self.home, "no-such-device"))
        self.assertIn("no-such-device does not exist", out)
        self.assertNotIn("ready", out)
        self.assertEqual(0, r.returncode, err)
        os.remove(os.path.join(self.fb.dir, "zbarcam"))
        r, out, err = self.run_pair(GOOD_LINE + "\n", "--no-listen", "--camera-device", self.camera)
        self.assertIn("zbarcam is not installed", out)
        self.assertEqual([], self.fb.ran())

    # -- misuse ------------------------------------------------------------------------------------------------------------------

    def test_without_a_terminal_and_without_stdin_it_refuses_to_guess(self):
        r = subprocess.run([sys.executable, PAIR] + self.args("--no-listen"), stdin=subprocess.DEVNULL, env=self.env(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
        self.assertEqual(2, r.returncode)
        self.assertIn(b"no terminal", r.stderr)
        self.assertNotIn(b"paddock://", r.stdout)
        self.assertIsNone(self.written())

    def test_bad_options_are_usage_errors(self):
        for extra in (["--timeout", "0"], ["--timeout", "-5"], ["--timeout", "99999"], ["--timeout", "abc"], ["--no-listen", "--listen-ip", "127.0.0.1"]):
            with self.subTest(extra):
                r, out, err = self.run_pair(GOOD_LINE + "\n", *extra)
                self.assertEqual(2, r.returncode)
                self.assertNotIn("paddock://", out)


# ---- the listener inside the popup -------------------------------------------------------------------------------------------------

def wire_ask(case, port, line, timeout=5):
    """One request on the wire, the way the app sends it; returns the reply word."""
    with socket.create_connection(("127.0.0.1", port), timeout=timeout) as s:
        s.sendall((line + "\n").encode())
        data = b""
        while not data.endswith(b"\n"):
            chunk = s.recv(100)
            if not chunk:
                break
            data += chunk
    case.assertTrue(data.startswith((V + " ").encode()) and data.endswith(b"\n"), data)
    return data.decode()[len(V) + 1:-1]


class PairProc(object):
    """bin/pair.py --stdin --listen-ip 127.0.0.1 running, with its standard input left open so the test types the answer when it wants."""

    def __init__(self, case, *extra, **env):
        self.case = case
        self.proc = subprocess.Popen([sys.executable, PAIR, "--stdin", "--listen-ip", "127.0.0.1", "--no-camera", "--no-qr"] + case.args(*extra),
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=case.env(**env))
        self.out = ""
        case.addCleanup(self.close)
        self.wait_for("for the phone (plain TCP")
        m = re.search(r"listening on 127\.0\.0\.1:(\d+) for the phone", self.out)
        case.assertTrue(m, self.out)
        self.port = int(m.group(1))
        fields = parse_link(case.link_in(self.out))
        self.sid = fields["sid"]
        case.assertEqual(str(self.port), fields["pair"])

    def wait_for(self, needle, timeout=10):
        end = time.time() + timeout
        while needle not in self.out and time.time() < end:
            r, _, _ = select.select([self.proc.stdout], [], [], 0.1)
            if r:
                chunk = os.read(self.proc.stdout.fileno(), 65536)
                if not chunk:
                    break
                self.out += chunk.decode("utf-8", "replace")
        self.case.assertIn(needle, self.out)

    def send(self, line):
        return wire_ask(self.case, self.port, line)

    def key(self, line=GOOD_LINE, sid=None):
        return self.send("%s key %s %s" % (V, sid or self.sid, line))

    def status(self, sid=None):
        return self.send("%s status %s" % (V, sid or self.sid))

    def type(self, text):
        self.proc.stdin.write(text.encode())
        self.proc.stdin.flush()

    def finish(self, timeout=20):
        try:
            self.proc.stdin.close()
        except OSError:
            pass
        code = self.proc.wait(timeout=timeout)
        self.out += self.proc.stdout.read().decode("utf-8", "replace")
        self.err = self.proc.stderr.read().decode("utf-8", "replace")
        return code

    def close(self):
        if self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait()
        for f in (self.proc.stdin, self.proc.stdout, self.proc.stderr):
            try:
                f.close()
            except OSError:
                pass


class PairListening(PairCase):
    def test_a_phone_key_over_the_wire_is_approved_and_written_and_the_phone_hears_ok(self):
        p = PairProc(self)
        self.assertEqual("none", p.status())
        self.assertEqual("pending", p.key())
        p.wait_for("A key arrived from the phone over the network (127.0.0.1)")
        p.wait_for("[R]eject (default) / [a]pprove")
        self.assertIn(GOOD_FINGERPRINT, p.out)
        self.assertEqual("pending", p.status(), "still waiting for the owner while the prompt is up")
        self.assertIsNone(self.written())
        self.assertEqual("busy", p.key(_other_key_line()), "a second, different key")
        self.assertEqual("refused", p.status(sid=pp.new_sid()))
        p.type("a\n")
        p.wait_for("Now press Connect on the phone")
        self.assertEqual("ok", p.status())
        self.assertEqual(0, p.finish(), p.out)
        self.assertEqual(reference_bytes(GOOD_LINE), self.written())
        self.assertIn(GOOD_FINGERPRINT, p.out)
        for t in (p.out, p.err):
            self.assertNotIn(GOOD_BODY, t)
            self.assertNotIn("paddock@phone", t)

    def test_an_active_ufw_is_named_with_the_commands_that_open_and_close_the_listeners_port(self):
        self.fb.script("systemctl", "import sys\nsys.exit(0 if sys.argv[-1] == 'ufw' else 3)\n", python=True)
        p = PairProc(self)
        p.wait_for("sudo ufw delete allow proto tcp to any port %d" % p.port)
        self.assertIn("ufw is running here", p.out)
        self.assertIn("sudo ufw allow proto tcp to any port %d\n" % p.port, p.out)
        self.assertNotIn("firewalld", p.out)

    def test_with_no_active_firewall_the_popup_says_nothing_about_one(self):
        self.fb.script("systemctl", "import sys\nsys.exit(3)\n", python=True)
        p = PairProc(self)
        p.wait_for("standard input (--stdin)")
        self.assertNotIn("is running here", p.out)  # not "ufw": the link's random fingerprint and handle could spell it
        self.assertNotIn("sudo ", p.out)

    def test_reject_is_told_to_the_phone_and_nothing_is_written(self):
        p = PairProc(self)
        p.key()
        p.wait_for("[R]eject (default) / [a]pprove")
        p.type("\n")
        p.wait_for("Rejected. Nothing was written.")
        self.assertEqual("rejected", p.status())
        self.assertEqual(1, p.finish(), "once the phone has been told, a script run ends")
        self.assertIsNone(self.written())

    def test_the_end_of_the_input_is_a_reject_and_the_waiting_phone_is_told(self):
        p = PairProc(self)
        p.key()
        p.wait_for("[R]eject (default) / [a]pprove")
        p.proc.stdin.close()
        p.wait_for("Rejected. Nothing was written.")
        self.assertEqual("rejected", p.status())
        self.assertEqual(1, p.finish())
        self.assertIsNone(self.written())

    def test_an_unanswered_prompt_expires_with_the_window_and_the_phone_is_told_expired(self):
        p = PairProc(self, "--timeout", "2")
        self.assertEqual("pending", p.key())
        p.wait_for("[R]eject (default) / [a]pprove")
        end = time.time() + 10
        word = "pending"
        while word == "pending" and time.time() < end:
            time.sleep(0.5)
            word = p.status()
        self.assertEqual("expired", word)
        p.wait_for("The time ran out before you answered. Nothing was written.")
        self.assertEqual(1, p.finish())
        self.assertIsNone(self.written())

    def test_nothing_arriving_in_the_window_writes_nothing_and_the_listener_closes(self):
        p = PairProc(self, "--timeout", "1")
        self.assertEqual(1, p.finish())
        self.assertIn("No key arrived within 1 seconds", p.err)
        with self.assertRaises(OSError):
            socket.create_connection(("127.0.0.1", p.port), timeout=1).close()

    def test_a_key_pasted_first_is_the_one_held_a_phone_with_another_key_is_busy_and_the_same_key_is_pending(self):
        p = PairProc(self)
        p.type(GOOD_LINE + "\n")
        p.wait_for("A key arrived from a pasted line")
        p.wait_for("[R]eject (default) / [a]pprove")
        self.assertEqual("busy", p.key(_other_key_line()))
        self.assertEqual("pending", p.key())
        p.type("a\n")
        p.wait_for("Now press Connect on the phone")
        self.assertEqual("ok", p.key(), "the phone that sent the same key hears the result")
        self.assertEqual(0, p.finish())
        self.assertEqual(reference_bytes(GOOD_LINE), self.written())

    def test_a_different_key_pasted_while_the_phones_prompt_is_up_is_an_answer_not_a_key_so_it_rejects(self):
        p = PairProc(self)
        p.key()
        p.wait_for("[R]eject (default) / [a]pprove")
        p.type(_other_key_line() + "\n")
        p.wait_for("Rejected. Nothing was written.")
        self.assertEqual("rejected", p.status())
        self.assertEqual(1, p.finish())
        self.assertIsNone(self.written())

    def test_a_wrong_sid_or_bad_key_from_the_network_does_not_end_the_popup_and_is_not_shown(self):
        p = PairProc(self)
        self.assertEqual("refused", p.key(sid=pp.new_sid()))
        self.assertEqual("refused", p.key(line="ecdsa-sha2-nistp256 AAAA " + MARK))
        self.assertEqual("none", p.status())
        self.assertIsNone(p.proc.poll(), "the popup is still waiting")
        self.assertEqual("pending", p.key())
        p.wait_for("[R]eject (default) / [a]pprove")
        p.type("a\n")
        p.wait_for("Now press Connect on the phone")
        self.assertEqual("ok", p.status())
        self.assertEqual(0, p.finish())
        self.assertNotIn(MARK, p.out + p.err)

    def test_the_listener_is_gone_when_the_popup_is_(self):
        p = PairProc(self)
        p.key()
        p.wait_for("[R]eject (default) / [a]pprove")
        p.type("\n")
        p.wait_for("Rejected. Nothing was written.")
        self.assertEqual("rejected", p.status())
        p.finish()
        with self.assertRaises(OSError):
            socket.create_connection(("127.0.0.1", p.port), timeout=1).close()

    def test_a_script_run_waits_a_few_seconds_for_a_phone_that_has_not_yet_heard_and_no_longer(self):
        p = PairProc(self)
        p.key()
        p.wait_for("[R]eject (default) / [a]pprove")
        p.type("\n")
        started = time.time()
        self.assertEqual(1, p.finish(timeout=30))
        waited = time.time() - started
        self.assertGreater(waited, 4, "it left before the phone could ask")
        self.assertLess(waited, 12)

    def test_a_script_run_does_not_wait_when_no_phone_was_involved(self):
        p = PairProc(self)
        p.type(GOOD_LINE + "\na\n")
        started = time.time()
        self.assertEqual(0, p.finish())
        self.assertLess(time.time() - started, 4)

    def test_a_sigterm_closes_the_listener_and_writes_nothing(self):
        p = PairProc(self)
        p.proc.send_signal(signal.SIGTERM)
        self.assertEqual(128 + signal.SIGTERM, p.proc.wait(timeout=10))
        with self.assertRaises(OSError):
            socket.create_connection(("127.0.0.1", p.port), timeout=1).close()
        self.assertIsNone(self.written())


def _other_key_line():
    import base64
    raw = bytearray(base64.b64decode(GOOD_BODY))
    raw[-1] ^= 1
    return "ecdsa-sha2-nistp256 " + base64.b64encode(bytes(raw)).decode() + " second@phone"


# ---- the terminal paths: a pty, so echo, Enter and the popup's pause are real --------------------------------------------------------

class PtyRun(object):
    def __init__(self, case, *extra, **env):
        ask_host = env.pop("ask_host", False)
        argv = case.args(*extra)
        if ask_host:
            del argv[argv.index("--host"):argv.index("--host") + 2]
        self.master, slave = pty.openpty()
        self.proc = subprocess.Popen([sys.executable, PAIR] + argv, stdin=slave, stdout=slave, stderr=slave, env=case.env(**env),
                                     close_fds=True, start_new_session=True)
        os.close(slave)
        self.screen = ""
        case.addCleanup(self.close)

    def pump(self, seconds=0.0):
        end = time.time() + seconds
        while True:
            r, _, _ = select.select([self.master], [], [], max(0.0, min(0.1, end - time.time())))
            if r:
                try:
                    data = os.read(self.master, 65536)
                except OSError:
                    return False
                if not data:
                    return False
                self.screen += data.decode("utf-8", "replace").replace("\r\n", "\n")
            elif time.time() >= end:
                return True

    def wait_for(self, needle, timeout=10):
        end = time.time() + timeout
        while needle not in self.screen and time.time() < end:
            if not self.pump(0.1):
                break
        return needle in self.screen

    def send(self, text):
        os.write(self.master, text.encode())

    def finish(self, timeout=10):
        end = time.time() + timeout
        while self.proc.poll() is None and time.time() < end:
            self.pump(0.1)
        self.pump(0.2)
        return self.proc.poll()

    def close(self):
        if self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait()
        try:
            os.close(self.master)
        except OSError:
            pass


@unittest.skipUnless(sys.platform.startswith("linux"), "pty test is Linux-only")
class PairTerminal(PairCase):
    def test_a_pasted_line_is_never_drawn_and_approval_writes_the_reference_bytes(self):
        t = PtyRun(self, "--no-listen", "--no-camera")
        self.assertTrue(t.wait_for("a pasted line: paste the key line here and press Enter (what you paste is not shown)"), t.screen)
        t.send(GOOD_LINE + "\n")
        self.assertTrue(t.wait_for("[R]eject (default) / [a]pprove"), t.screen)
        self.assertNotIn(GOOD_BODY[:40], t.screen, "the pasted line was echoed to the screen")
        self.assertNotIn("paddock@phone", t.screen)
        self.assertIn(GOOD_FINGERPRINT, t.screen)
        self.assertIn("[StLaLXC/]", t.screen)
        self.assertIsNone(self.written(), "nothing is written before the answer")
        t.send("a\n")
        self.assertTrue(t.wait_for("Now press Connect on the phone"), t.screen)
        self.assertTrue(t.wait_for("Press Enter to close."), t.screen)
        self.assertIsNone(t.proc.poll(), "the popup stays open until Enter so the text can be read")
        t.send("\n")
        self.assertEqual(0, t.finish(), t.screen)
        self.assertEqual(reference_bytes(GOOD_LINE), self.written())
        self.assertNotIn(GOOD_BODY[:40], t.screen)

    def test_an_empty_answer_rejects_and_so_does_r(self):
        for answer in ("\n", "R\n", "x\n"):
            with self.subTest(answer=answer):
                t = PtyRun(self, "--no-listen", "--no-camera")
                self.assertTrue(t.wait_for("paste the key line here"))
                t.send(GOOD_LINE + "\n")
                self.assertTrue(t.wait_for("[R]eject (default) / [a]pprove"))
                t.send(answer)
                self.assertTrue(t.wait_for("Rejected. Nothing was written."), t.screen)
                self.assertTrue(t.wait_for("Press Enter to close."))
                t.send("\n")
                self.assertEqual(1, t.finish())
                self.assertIsNone(self.written())

    def test_a_refused_paste_is_explained_not_shown_and_the_popup_waits_for_enter(self):
        t = PtyRun(self, "--no-listen", "--no-camera")
        self.assertTrue(t.wait_for("paste the key line here"))
        t.send("-----BEG" + "IN OPENSSH PRIV" + "ATE KEY-----" + MARK + "\n")
        self.assertTrue(t.wait_for("looks like a private key"), t.screen)
        self.assertTrue(t.wait_for("Press Enter to close."))
        self.assertNotIn(MARK, t.screen)
        self.assertNotIn("OPENSSH", t.screen)
        t.send("\n")
        self.assertEqual(2, t.finish())
        self.assertIsNone(self.written())

    def test_an_empty_enter_without_a_camera_changes_nothing_and_the_paste_still_works(self):
        t = PtyRun(self, "--no-listen", "--no-camera")
        self.assertTrue(t.wait_for("paste the key line here"))
        t.send("\n\n")
        t.pump(0.5)
        self.assertIsNone(t.proc.poll())
        self.assertNotIn("Camera on", t.screen)
        t.send(GOOD_LINE + "\n")
        self.assertTrue(t.wait_for("[R]eject (default) / [a]pprove"))
        t.send("a\n")
        self.assertTrue(t.wait_for("Now press Connect on the phone"))
        t.send("\n")
        self.assertEqual(0, t.finish())

    def test_the_camera_is_switched_on_only_by_enter_and_a_code_it_reads_goes_to_the_prompt(self):
        self.fb.zbarcam(GOOD_LINE)
        t = PtyRun(self, "--no-listen", "--camera-device", self.camera)
        self.assertTrue(t.wait_for("camera %s ready (turns on after you press Enter" % self.camera), t.screen)
        self.assertTrue(t.wait_for("paste the key line here"))
        t.pump(0.7)
        self.assertEqual([], self.fb.ran(), "the camera was started before Enter")
        self.assertNotIn("Camera on", t.screen)
        t.send("\n")
        self.assertTrue(t.wait_for("Camera on"), t.screen)
        self.assertTrue(t.wait_for("A key arrived from the camera"), t.screen)
        self.assertTrue(t.wait_for("[R]eject (default) / [a]pprove"), t.screen)
        self.assertEqual(["--raw --oneshot --nodisplay --prescale=640x480 " + self.camera], self.fb.ran())
        self.assertIsNone(self.written())
        t.send("a\n")
        self.assertTrue(t.wait_for("Now press Connect on the phone"), t.screen)
        t.send("\n")
        self.assertEqual(0, t.finish())
        self.assertEqual(reference_bytes(GOOD_LINE), self.written())
        self.assertNotIn(GOOD_BODY[:40], t.screen)
        self.assertTrue(self.fb.gone())

    def test_a_second_enter_does_not_start_a_second_camera(self):
        self.fb.zbarcam(None, hang=True)
        t = PtyRun(self, "--no-listen", "--camera-device", self.camera)
        self.assertTrue(t.wait_for("paste the key line here"))
        t.send("\n")
        self.assertTrue(t.wait_for("Camera on"))
        t.send("\n\n")
        t.pump(0.5)
        self.assertEqual(1, len(self.fb.ran()))
        self.assertEqual(1, t.screen.count("Camera on"))

    def test_a_paste_while_the_camera_is_on_wins_and_the_camera_is_switched_off(self):
        self.fb.zbarcam(None, hang=True)
        t = PtyRun(self, "--no-listen", "--camera-device", self.camera)
        self.assertTrue(t.wait_for("paste the key line here"))
        t.send("\n")
        self.assertTrue(t.wait_for("Camera on"))
        t.send(GOOD_LINE + "\n")
        self.assertTrue(t.wait_for("[R]eject (default) / [a]pprove"), t.screen)
        self.assertIn("Camera off", t.screen)
        self.assertTrue(self.fb.gone(), "zbarcam must be killed when another intake wins")
        t.send("\n")
        t.wait_for("Press Enter to close.")
        t.send("\n")
        self.assertEqual(1, t.finish())

    def test_closing_the_popup_while_the_camera_is_on_switches_it_off(self):
        for sig in (signal.SIGHUP, signal.SIGTERM):
            with self.subTest(sig=sig.name):
                self.fb.zbarcam(None, hang=True)
                t = PtyRun(self, "--no-listen", "--camera-device", self.camera)
                self.assertTrue(t.wait_for("paste the key line here"))
                t.send("\n")
                self.assertTrue(t.wait_for("Camera on"))
                t.pump(0.3)
                t.proc.send_signal(sig)
                self.assertEqual(128 + sig, t.finish())
                self.assertTrue(self.fb.gone(), "zbarcam kept running after the popup was closed")
                self.assertIsNone(self.written())

    def test_a_lost_ok_or_rejected_can_be_asked_for_again_until_the_popup_is_closed(self):
        for answer, word, code in (("a\n", "ok", 0), ("\n", "rejected", 1)):
            with self.subTest(word=word):
                shutil.rmtree(os.path.join(self.home, ".ssh"), ignore_errors=True)
                t = PtyRun(self, "--no-camera", "--no-qr", "--listen-ip", "127.0.0.1")
                self.assertTrue(t.wait_for("for the phone (plain TCP"), t.screen)
                port = int(re.search(r"listening on 127\.0\.0\.1:(\d+) for the phone", t.screen).group(1))
                sid = parse_link(self.link_in(t.screen))["sid"]
                self.assertEqual("none", wire_ask(self, port, "%s status %s" % (V, sid)))
                self.assertEqual("pending", wire_ask(self, port, "%s key %s %s" % (V, sid, GOOD_LINE)))
                self.assertTrue(t.wait_for("A key arrived from the phone over the network (127.0.0.1)"), t.screen)
                self.assertTrue(t.wait_for("[R]eject (default) / [a]pprove"))
                self.assertEqual("pending", wire_ask(self, port, "%s status %s" % (V, sid)), "the listener keeps answering while the prompt is up")
                t.send(answer)
                self.assertTrue(t.wait_for("Press Enter to close."), t.screen)
                for _ in range(3):
                    self.assertEqual(word, wire_ask(self, port, "%s status %s" % (V, sid)))
                self.assertEqual(word, wire_ask(self, port, "%s key %s %s" % (V, sid, GOOD_LINE)))
                self.assertIsNone(t.proc.poll(), "the popup is still open, so the phone can still ask")
                t.send("\n")
                self.assertEqual(code, t.finish(), t.screen)
                with self.assertRaises(OSError):
                    socket.create_connection(("127.0.0.1", port), timeout=1).close()
                self.assertNotIn(GOOD_BODY[:40], t.screen)
                self.assertEqual(reference_bytes(GOOD_LINE) if word == "ok" else None, self.written())

    def test_a_refusal_that_ends_the_run_stops_the_listener_holding_keys(self):
        # junk from the paste or the camera ends the run; the popup stays open on Enter, and a phone key that arrives then has no prompt
        # to come to: it must be told `expired` (final), not `pending` for a window that nobody is watching
        for intake in ("paste", "camera"):
            with self.subTest(intake=intake):
                if intake == "paste":
                    t = PtyRun(self, "--no-camera", "--no-qr", "--listen-ip", "127.0.0.1")
                else:
                    self.fb.zbarcam("https://example.org/" + MARK)
                    t = PtyRun(self, "--no-qr", "--listen-ip", "127.0.0.1", "--camera-now", "--camera-device", self.camera)
                self.assertTrue(t.wait_for("for the phone (plain TCP"), t.screen)
                port = int(re.search(r"listening on 127\.0\.0\.1:(\d+) for the phone", t.screen).group(1))
                sid = parse_link(self.link_in(t.screen))["sid"]
                if intake == "paste":
                    t.send("this is not a key line\n")
                self.assertTrue(t.wait_for("Refused (%s)" % ("a pasted line" if intake == "paste" else "the camera")), t.screen)
                self.assertTrue(t.wait_for("Press Enter to close."), t.screen)
                self.assertIsNone(t.proc.poll(), "the popup is still open, so the listener is still up")
                self.assertEqual("expired", wire_ask(self, port, "%s key %s %s" % (V, sid, GOOD_LINE)))
                self.assertEqual("none", wire_ask(self, port, "%s status %s" % (V, sid)), "the key was not stored")
                self.assertEqual("expired", wire_ask(self, port, "%s key %s %s" % (V, sid, GOOD_LINE)))
                self.assertEqual("refused", wire_ask(self, port, "%s status %s" % (V, pp.new_sid())), "everything else is answered as before")
                self.assertNotIn("A key arrived", t.screen)
                t.send("\n")
                self.assertEqual(2, t.finish(), t.screen)
                self.assertIsNone(self.written())
                self.assertNotIn(MARK, t.screen)

    def test_the_default_listener_comes_from_the_default_route_and_a_missing_address_is_said(self):
        self.fb.ip("127.0.0.1")
        t = PtyRun(self, "--no-camera")
        self.assertTrue(t.wait_for("listening on 127.0.0.1:"), t.screen)
        m = re.search(r"listening on 127\.0\.0\.1:(\d+) for the phone", t.screen)
        self.assertIn("&pair=%s&sid=" % m.group(1), self.link_in(t.screen))
        t.close()
        os.remove(os.path.join(self.fb.dir, "ip"))
        t = PtyRun(self, "--no-camera")
        self.assertTrue(t.wait_for("listener: off (no LAN address was found"), t.screen)
        self.assertNotIn("&pair=", self.link_in(t.screen))

    def test_no_listen_turns_the_listener_off_even_when_an_address_exists(self):
        self.fb.ip("127.0.0.1")
        t = PtyRun(self, "--no-camera", "--no-listen")
        self.assertTrue(t.wait_for("listener: off (--no-listen)"), t.screen)
        self.assertEqual(self.base_link, self.link_in(t.screen))

    def test_the_host_name_is_asked_like_show_pairing_asks_it(self):
        self.fb.ip("10.9.8.7")
        t = PtyRun(self, "--no-listen", "--no-camera", "--no-qr", ask_host=True)
        self.assertTrue(t.wait_for("Host name or address the phone should use [10.9.8.7]"), t.screen)
        t.send("phone-box.local\n")
        self.assertTrue(t.wait_for("paste the key line here"), t.screen)
        self.assertEqual("paddock://pair?v=1&host=phone-box.local&port=22&user=alice&fp=" + self.fp, self.link_in(t.screen))
        t.close()
        t = PtyRun(self, "--no-listen", "--no-camera", "--no-qr", ask_host=True)
        self.assertTrue(t.wait_for("Host name or address the phone should use ["))
        t.send("\n")
        self.assertTrue(t.wait_for("paste the key line here"), t.screen)
        self.assertIn("host=10.9.8.7&", self.link_in(t.screen), "Enter keeps the default, and the default is the LAN address")

    def test_with_no_lan_address_the_default_is_the_host_name(self):
        t = PtyRun(self, "--no-listen", "--no-camera", "--no-qr", ask_host=True)  # no `ip` on this PATH
        self.assertTrue(t.wait_for("Host name or address the phone should use [%s]" % socket.gethostname()), t.screen)


if __name__ == "__main__":
    unittest.main()
