import importlib.util
import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

from support import ROOT

spec = importlib.util.spec_from_file_location("check_pins", os.path.join(ROOT, "tools", "check_pins.py"))
check_pins = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_pins)


class CheckPins(unittest.TestCase):
    """The plugin tree is copied next to a stand-in app repository so each test can break one thing at a time."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.plugin = os.path.join(self._tmp.name, "plugin")
        self.app = os.path.join(self._tmp.name, "app")
        os.makedirs(os.path.join(self.plugin, "host"))
        os.makedirs(os.path.join(self.app, "host"))
        for n in ("paddock-relay.py", "paddock-control.py", "SOURCE.json"):
            shutil.copy(os.path.join(ROOT, "host", n), os.path.join(self.plugin, "host", n))
        shutil.copy(os.path.join(ROOT, "herdr-plugin.toml"), self.plugin)
        # the stand-in app repository: the same two scripts, and a SOURCE.json holding the pins and more entries than the plugin ships
        for n in ("paddock-relay.py", "paddock-control.py"):
            shutil.copy(os.path.join(ROOT, "host", n), os.path.join(self.app, "host", n))
        mirror = self.load(self.plugin)
        app = dict(mirror)
        for k in ("plugin", "plugin_version", "pins"):
            app.pop(k)
        app["files"] = dict(mirror["files"], **{"host/paddock-decide.py": "sha256:" + "0" * 64})
        app["decide"] = "paddock-decide.py"
        self.save(self.app, app)

    def tearDown(self):
        self._tmp.cleanup()

    def load(self, root):
        with open(os.path.join(root, "host", "SOURCE.json")) as f:
            return json.load(f)

    def save(self, root, data):
        with open(os.path.join(root, "host", "SOURCE.json"), "w") as f:
            json.dump(data, f)

    def run_it(self, *args):
        out = io.StringIO()
        with redirect_stdout(out), redirect_stderr(out):
            code = check_pins.main(["--root", self.plugin, "--app-repo", self.app] + list(args))
        return code, out.getvalue()

    def edit(self, root, fn):
        data = self.load(root)
        fn(data)
        self.save(root, data)

    def test_it_passes_when_everything_agrees_and_the_app_pins_more_scripts_than_the_plugin_ships(self):
        code, out = self.run_it()
        self.assertEqual(0, code, out)
        self.assertIn("0 failed", out)

    def test_a_changed_shipped_script_fails(self):
        with open(os.path.join(self.plugin, "host", "paddock-relay.py"), "ab") as f:
            f.write(b"# one more byte\n")
        code, out = self.run_it()
        self.assertEqual(1, code)
        self.assertIn("FAIL  paddock-relay.py: the shipped file hashes to the pin", out)
        self.assertIn("FAIL  paddock-relay.py: byte-identical to the app repository's copy", out)

    def test_a_new_app_pin_that_the_plugin_has_not_taken_fails(self):
        self.edit(self.app, lambda d: d["files"].update({"host/paddock-control.py": "sha256:" + "1" * 64}))
        code, out = self.run_it()
        self.assertEqual(1, code)
        self.assertIn("FAIL  paddock-control.py: the mirror equals the app's pin", out)

    def test_a_wrong_mirror_fails(self):
        self.edit(self.plugin, lambda d: d["files"].update({"host/paddock-relay.py": "sha256:" + "2" * 64}))
        code, out = self.run_it()
        self.assertEqual(1, code)
        self.assertIn("FAIL  paddock-relay.py: the mirror equals the app's pin", out)

    def test_version_and_name_mismatches_fail(self):
        self.edit(self.app, lambda d: d.update({"control_version": 2}))
        code, out = self.run_it()
        self.assertEqual(1, code)
        self.assertIn("FAIL  control: version equals the app's", out)
        self.edit(self.app, lambda d: d.update({"relay": "paddock-relay2.py"}))
        self.assertIn("FAIL  relay: script name equals the app's", self.run_it()[1])

    def test_an_unpinned_extra_script_fails(self):
        with open(os.path.join(self.plugin, "host", "paddock-decide.py"), "w") as f:
            f.write("print('not pinned here')\n")
        code, out = self.run_it()
        self.assertEqual(1, code)
        self.assertIn("FAIL  no unpinned script is shipped", out)

    def test_a_manifest_version_that_differs_from_the_mirror_fails(self):
        path = os.path.join(self.plugin, "herdr-plugin.toml")
        with open(path) as f:
            t = f.read().replace('version = "0.1.0"', 'version = "0.2.0"', 1)
        with open(path, "w") as f:
            f.write(t)
        code, out = self.run_it()
        self.assertEqual(1, code)
        self.assertIn("FAIL  manifest version equals the mirror's plugin_version", out)

    def test_sync_copies_the_scripts_and_rewrites_the_mirror(self):
        with open(os.path.join(self.app, "host", "paddock-relay.py"), "ab") as f:
            f.write(b"# a newer relay\n")
        new = check_pins.sha(os.path.join(self.app, "host", "paddock-relay.py"))
        self.edit(self.app, lambda d: d["files"].update({"host/paddock-relay.py": new}) or d.update({"version": 2}))
        self.assertEqual(1, self.run_it()[0])
        code, out = self.run_it("--sync")
        self.assertEqual(0, code, out)
        self.assertEqual(new, self.load(self.plugin)["files"]["host/paddock-relay.py"])
        self.assertEqual(2, self.load(self.plugin)["version"])
        self.assertEqual(self.load(self.plugin)["plugin_version"], "0.1.0", "sync keeps the plugin's own fields")

    def test_a_missing_app_repository_is_an_error_not_a_pass(self):
        shutil.rmtree(os.path.join(self.app, "host"))
        code, out = self.run_it()
        self.assertEqual(2, code)
        self.assertIn("pass --app-repo", out)

    def test_the_real_app_repository_agrees_when_it_is_there(self):
        app = os.environ.get("PADDOCK_APP_REPO") or os.path.join(os.path.dirname(ROOT), "paddock-android")
        if not os.path.isfile(os.path.join(app, "host", "SOURCE.json")):
            self.skipTest("the Paddock app repository is not next to this one")
        out = io.StringIO()
        with redirect_stdout(out), redirect_stderr(out):
            code = check_pins.main(["--app-repo", app])
        self.assertEqual(0, code, out.getvalue())


if __name__ == "__main__":
    unittest.main()
