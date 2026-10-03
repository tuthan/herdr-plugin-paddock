import os
import stat
import subprocess
import sys
import tempfile
import unittest

from support import BIN


class OpenPane(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.log = os.path.join(self._tmp.name, "argv.txt")
        self.fake = os.path.join(self._tmp.name, "herdr")

    def tearDown(self):
        self._tmp.cleanup()

    def fake_herdr(self, stdout="", code=0):
        with open(self.fake, "w") as f:
            f.write("#!/bin/sh\nprintf '%%s\\n' \"$@\" > %s\nprintf '%%s' '%s'\nexit %d\n" % (self.log, stdout, code))
        os.chmod(self.fake, 0o755)

    def run_it(self, *args, **env):
        e = {k: v for k, v in os.environ.items() if not k.startswith("HERDR_")}
        e["HERDR_BIN_PATH"] = self.fake
        e.update(env)
        return subprocess.run([sys.executable, os.path.join(BIN, "open_pane.py")] + list(args), env=e, stdin=subprocess.DEVNULL,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20)

    def argv(self):
        with open(self.log) as f:
            return f.read().split("\n")[:-1]

    def test_it_opens_the_pane_of_the_same_name_through_the_herdr_binary_herdr_names(self):
        self.fake_herdr('{"id":"x","result":{"type":"ok"}}')
        for entry in ("authorize-phone", "show-pairing"):
            r = self.run_it(entry, HERDR_PLUGIN_ID="paddock")
            self.assertEqual(0, r.returncode, r.stderr)
            self.assertEqual(["plugin", "pane", "open", "--plugin", "paddock", "--entrypoint", entry], self.argv())

    def test_extra_arguments_go_to_herdr_unchanged(self):
        self.fake_herdr('{"result":{"type":"ok"}}')
        self.run_it("authorize-phone", "--placement", "split", "--no-focus")
        self.assertEqual(["plugin", "pane", "open", "--plugin", "paddock", "--entrypoint", "authorize-phone", "--placement", "split", "--no-focus"], self.argv())

    def test_a_busy_popup_is_reported_plainly(self):
        self.fake_herdr('{"error":{"code":"ui_busy","message":"a popup pane is already open"},"id":"cli:plugin"}')
        r = self.run_it("show-pairing")
        self.assertEqual(1, r.returncode)
        self.assertIn("a popup pane is already open", r.stderr.decode())
        self.assertIn("ui_busy", r.stderr.decode())

    def test_only_the_two_known_entrypoints_are_accepted(self):
        self.fake_herdr('{"result":{"type":"ok"}}')
        for args in ([], ["--help"], ["rm"], ["authorize-phone;id"], ["../x"]):
            with self.subTest(args):
                r = self.run_it(*args)
                self.assertEqual(2, r.returncode)
                self.assertFalse(os.path.exists(self.log), "herdr must not be called for an unknown entrypoint")

    def test_a_missing_herdr_is_an_error_not_a_traceback(self):
        r = self.run_it("authorize-phone", HERDR_BIN_PATH=os.path.join(self._tmp.name, "nope"))
        self.assertEqual(1, r.returncode)
        self.assertNotIn("Traceback", r.stderr.decode())


if __name__ == "__main__":
    unittest.main()
