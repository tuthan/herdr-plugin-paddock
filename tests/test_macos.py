"""The macOS paths of the plugin's library: LAN address and network, the clipboard, the firewall note and the camera message.

Nothing here runs on a Mac. Each path is driven with stand-ins for the macOS programs (route, ipconfig, ifconfig, pbcopy, socketfilterfw) that
print what those programs print, and every function takes `platform` so the Linux machine that runs the tests can ask for the macOS answer. The
Linux answers must not change, so each macOS case has a Linux counterpart that checks the other programs are never reached.
"""
import os
import subprocess
import unittest

from test_pair import FakeBin
import paddock_plugin as pp

ROUTE_GET_DEFAULT = b"""   route to: default
destination: default
       mask: default
    gateway: 192.168.42.1
  interface: en0
      flags: <UP,GATEWAY,DONE,STATIC,PRCLONING,GLOBAL>
 recvpipe  sendpipe  ssthresh  rtt,msec    rttvar  hopcount      mtu     expire
       0         0         0         0         0         0      1500         0
"""

IFCONFIG = b"""lo0: flags=8049<UP,LOOPBACK,RUNNING,MULTICAST> mtu 16384
\toptions=1203<RXCSUM,TXCSUM,TXSTATUS,SW_TIMESTAMP>
\tinet 127.0.0.1 netmask 0xff000000
\tinet6 ::1 prefixlen 128
en0: flags=8863<UP,BROADCAST,SMART,RUNNING,SIMPLEX,MULTICAST> mtu 1500
\tether 02:00:5e:10:00:01
\tinet6 fe80::1c2f:aaaa:bbbb:cccc%en0 prefixlen 64 secured scopeid 0xb
\tinet 192.168.42.23 netmask 0xffffff00 broadcast 192.168.42.255
\tnd6 options=201<PERFORMNUD,DAD>
\tmedia: autoselect
\tstatus: active
utun3: flags=8051<UP,POINTOPOINT,RUNNING,MULTICAST> mtu 1380
\tinet 100.64.0.7 --> 100.64.0.7 netmask 0xffffffff
"""

ROUTE = ["route", "-n", "get", "default"]
FIREWALL = [pp.MACOS_FIREWALL, "--getglobalstate"]


def runner(answers, calls=None):
    """A stand-in for subprocess.run: [answers] maps a command to (exit code, stdout). A command that is not in it is a program that is not installed."""
    def run(cmd, **kw):
        if calls is not None:
            calls.append(list(cmd))
        try:
            code, out = answers[tuple(cmd)]
        except KeyError:
            raise FileNotFoundError(2, "No such file or directory", cmd[0])
        return subprocess.CompletedProcess(cmd, code, out, b"")
    return run


class MacosLanAddress(unittest.TestCase):
    def test_it_is_the_address_of_the_default_routes_interface(self):
        calls = []
        run = runner({tuple(ROUTE): (0, ROUTE_GET_DEFAULT), ("ipconfig", "getifaddr", "en0"): (0, b"192.168.42.23\n")}, calls)
        self.assertEqual("192.168.42.23", pp.lan_address(run, "darwin"))
        self.assertEqual([ROUTE, ["ipconfig", "getifaddr", "en0"]], calls, "`ip` is never reached on macOS")

    def test_default_host_is_that_address_and_the_host_name_only_without_one(self):
        run = runner({tuple(ROUTE): (0, ROUTE_GET_DEFAULT), ("ipconfig", "getifaddr", "en0"): (0, b"192.168.42.23\n")})
        self.assertEqual("192.168.42.23", pp.default_host(run, "darwin"))
        import socket
        self.assertEqual(socket.gethostname(), pp.default_host(runner({}), "darwin"))

    def test_a_vpn_default_route_whose_interface_has_no_address_gives_none(self):
        vpn = ROUTE_GET_DEFAULT.replace(b"en0", b"utun3")
        run = runner({tuple(ROUTE): (0, vpn), ("ipconfig", "getifaddr", "utun3"): (1, b"")})
        self.assertIsNone(pp.lan_address(run, "darwin"))

    def test_anything_odd_gives_none(self):
        for name, answers in (
            ("no route command", {}),
            ("route fails", {tuple(ROUTE): (1, b"route: writing to routing socket: not in table\n")}),
            ("no interface line", {tuple(ROUTE): (0, b"   route to: default\n    gateway: 192.168.42.1\n")}),
            ("ipconfig missing", {tuple(ROUTE): (0, ROUTE_GET_DEFAULT)}),
            ("ipconfig prints text", {tuple(ROUTE): (0, ROUTE_GET_DEFAULT), ("ipconfig", "getifaddr", "en0"): (0, b"not an address\n")}),
            ("ipconfig prints 0.0.0.0", {tuple(ROUTE): (0, ROUTE_GET_DEFAULT), ("ipconfig", "getifaddr", "en0"): (0, b"0.0.0.0\n")}),
            ("ipconfig prints an IPv6 address", {tuple(ROUTE): (0, ROUTE_GET_DEFAULT), ("ipconfig", "getifaddr", "en0"): (0, b"fe80::1\n")}),
        ):
            with self.subTest(name):
                self.assertIsNone(pp.lan_address(runner(answers), "darwin"))

    def test_an_interface_name_that_is_not_a_plain_name_is_never_passed_on(self):
        calls = []
        evil = ROUTE_GET_DEFAULT.replace(b"en0", b"en0;touch")
        self.assertIsNone(pp.lan_address(runner({tuple(ROUTE): (0, evil)}, calls), "darwin"))
        self.assertEqual([ROUTE], calls)

    def test_on_linux_route_and_ipconfig_are_never_reached(self):
        calls = []
        pp.lan_address(runner({}, calls), "linux")
        self.assertEqual([["ip", "-json", "-4", "route", "show", "default"]], calls)


class MacosLanNetwork(unittest.TestCase):
    def ask(self, ip_text, out=IFCONFIG, answers=None):
        return pp.lan_network(ip_text, runner(answers if answers is not None else {("ifconfig",): (0, out)}), "darwin")

    def test_it_is_the_network_the_address_is_on_from_the_hexadecimal_mask(self):
        self.assertEqual("192.168.42.0/24", self.ask("192.168.42.23"))
        self.assertEqual("10.1.0.0/16", self.ask("10.1.2.3", b"\tinet 10.1.2.3 netmask 0xffff0000 broadcast 10.1.255.255\n"))
        self.assertEqual("172.16.8.0/21", self.ask("172.16.9.4", b"\tinet 172.16.9.4 netmask 0xfffff800 broadcast 172.16.15.255\n"))

    def test_an_address_ifconfig_does_not_list_gives_none(self):
        self.assertIsNone(self.ask("192.168.42.99"))

    def test_a_mask_that_is_not_a_run_of_ones_gives_none(self):
        self.assertIsNone(self.ask("10.1.2.3", b"\tinet 10.1.2.3 netmask 0xff00ff00 broadcast 10.255.255.255\n"))

    def test_a_point_to_point_line_and_a_missing_ifconfig_give_none(self):
        self.assertIsNone(self.ask("100.64.0.7"), "`inet A --> A netmask ...` is a tunnel, not a LAN")
        self.assertIsNone(self.ask("192.168.42.23", answers={}))
        self.assertIsNone(self.ask("192.168.42.23", answers={("ifconfig",): (1, b"")}))

    def test_on_linux_ifconfig_is_never_reached(self):
        calls = []
        pp.lan_network("192.168.42.23", runner({}, calls), "linux")
        self.assertEqual([["ip", "-json", "-4", "addr", "show"]], calls)


class MacosClipboard(unittest.TestCase):
    def tool(self, fb, name):
        out = os.path.join(fb._tmp.name, name + "-got")
        fb.script(name, "import sys\nopen(%r, 'w').write(sys.stdin.read() + '|' + ' '.join(sys.argv[1:]))\n" % out, python=True)
        return out

    def got(self, path):
        try:
            with open(path) as f:
                return f.read()
        except OSError:
            return None

    def with_path(self, fb):
        import unittest.mock as mock
        return mock.patch.dict(os.environ, {"PATH": fb.dir})

    def test_pbcopy_gets_exactly_the_text_and_needs_no_display_variable(self):
        with FakeBin() as fb:
            out = self.tool(fb, "pbcopy")
            with self.with_path(fb):
                self.assertEqual("pbcopy", pp.copy_to_clipboard("paddock://pair?v=1", env={}, platform="darwin"))
            self.assertEqual("paddock://pair?v=1|", self.got(out))

    def test_the_x11_tools_are_not_used_on_macos_even_with_a_display(self):
        with FakeBin() as fb:
            xclip, wl = self.tool(fb, "xclip"), self.tool(fb, "wl-copy")
            with self.with_path(fb):
                self.assertIsNone(pp.copy_to_clipboard("L", env={"DISPLAY": ":0", "WAYLAND_DISPLAY": "w"}, platform="darwin"))
            self.assertIsNone(self.got(xclip), "XQuartz's clipboard is not the one Cmd+V reads")
            self.assertIsNone(self.got(wl))

    def test_pbcopy_is_not_used_on_linux(self):
        with FakeBin() as fb:
            out = self.tool(fb, "pbcopy")
            with self.with_path(fb):
                self.assertIsNone(pp.copy_to_clipboard("L", env={"WAYLAND_DISPLAY": "w", "DISPLAY": ":0"}, platform="linux"))
            self.assertIsNone(self.got(out))

    def test_the_names_in_the_messages_are_the_platforms_tools(self):
        self.assertEqual("pbcopy", pp.clipboard_tool_names("darwin"))
        self.assertEqual("wl-copy, xclip, xsel", pp.clipboard_tool_names("linux"))


class MacosFirewall(unittest.TestCase):
    def note(self, out, code=0, calls=None):
        return pp.firewall_note(45173, "192.168.42.0/24", runner({tuple(FIREWALL): (code, out)}, calls), "darwin")

    def test_a_firewall_that_is_on_asks_the_owner_to_click_allow_and_runs_nothing_that_changes_it(self):
        calls = []
        note = self.note(b"Firewall is enabled. (State = 1)\n", calls=calls)
        self.assertIn("macOS firewall is on", note)
        self.assertIn("click Allow", note)
        self.assertNotIn("sudo", note)
        self.assertEqual([FIREWALL], calls, "only the read-only state is asked, and systemctl is never reached")

    def test_block_all_incoming_says_to_turn_that_off(self):
        note = self.note(b"Firewall is on, blocking all incoming connections. (State = 2)\n")
        self.assertIn("Block all incoming connections", note)
        self.assertIn("block all incoming", note)

    def test_off_unknown_or_unavailable_says_nothing(self):
        self.assertIsNone(self.note(b"Firewall is disabled. (State = 0)\n"))
        self.assertIsNone(self.note(b"something else entirely\n"))
        self.assertIsNone(self.note(b"", code=1))
        self.assertIsNone(pp.firewall_note(45173, None, runner({}), "darwin"))

        def hangs(cmd, **kw):
            raise subprocess.TimeoutExpired(cmd, 5)
        self.assertIsNone(pp.firewall_note(45173, None, hangs, "darwin"))

    def test_on_linux_socketfilterfw_is_never_reached(self):
        calls = []
        pp.firewall_note(45173, None, runner({}, calls), "linux")
        self.assertTrue(calls and all(c[0] == "systemctl" for c in calls), calls)


class CameraBlocker(unittest.TestCase):
    def test_macos_says_why_there_is_no_camera_and_what_to_use_instead(self):
        reason = pp.camera_blocker("darwin")
        self.assertTrue(reason.startswith("camera: off"))
        self.assertIn("paste", reason)
        self.assertIn("listener", reason)

    def test_linux_has_no_blocker_of_its_own(self):
        self.assertIsNone(pp.camera_blocker("linux"))

    def test_is_macos_only_for_darwin(self):
        self.assertTrue(pp.is_macos("darwin"))
        for other in ("linux", "win32", "freebsd14"):
            self.assertFalse(pp.is_macos(other))


if __name__ == "__main__":
    unittest.main()
