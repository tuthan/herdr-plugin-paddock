import os
import re
import unittest

from support import ROOT

try:
    import tomllib
except ImportError:  # Python before 3.11: the checks that need a parser are skipped, the text checks below still run
    tomllib = None


def text():
    with open(os.path.join(ROOT, "herdr-plugin.toml")) as f:
        return f.read()


class Manifest(unittest.TestCase):
    def test_the_required_fields_and_the_pinned_herdr_version(self):
        t = text()
        for field, value in (("id", "tuthan.paddock"), ("name", "Paddock"), ("version", "0.2.0"), ("min_herdr_version", "0.9.1")):
            self.assertRegex(t, r'(?m)^%s = "%s"$' % (field, re.escape(value)))

    def test_no_build_startup_or_event_hooks_so_nothing_runs_unless_the_user_picks_an_action(self):
        t = text()
        for section in ("[[build]]", "[[startup]]", "[[events]]", "[[link_handlers]]", "[[keys.command]]"):
            self.assertNotIn(section, t)

    @unittest.skipIf(tomllib is None, "tomllib needs Python 3.11")
    def test_parsed(self):
        m = tomllib.loads(text())
        self.assertEqual(["linux", "macos"], m["platforms"])
        actions = {a["id"]: a for a in m["actions"]}
        panes = {p["id"]: p for p in m["panes"]}
        self.assertEqual({"authorize-phone", "show-pairing", "pair"}, set(actions))
        self.assertEqual(3, len(m["actions"]))
        self.assertEqual(3, len(m["panes"]))
        self.assertEqual(set(actions), set(panes), "each action opens the pane of the same name")
        for aid, a in actions.items():
            # argv, no shell; the script exists relative to the plugin root (herdr runs commands from there)
            self.assertEqual(["python3", "bin/open_pane.py", aid], a["command"])
            self.assertTrue(os.path.isfile(os.path.join(ROOT, a["command"][1])))
        for pid, p in panes.items():
            self.assertEqual("popup", p["placement"])
            self.assertEqual("python3", p["command"][0])
            self.assertTrue(os.path.isfile(os.path.join(ROOT, p["command"][1])))
        self.assertEqual("bin/authorize_phone.py", panes["authorize-phone"]["command"][1])
        self.assertEqual("bin/show_pairing.py", panes["show-pairing"]["command"][1])
        self.assertEqual("bin/pair.py", panes["pair"]["command"][1])
        self.assertEqual("Paddock: pair a phone", actions["pair"]["title"])
        self.assertEqual(("90%", "90%"), (panes["pair"]["width"], panes["pair"]["height"]))
        for ident in list(actions) + list(panes):
            self.assertRegex(ident, r"^[A-Za-z0-9:_-]+$", "action and pane ids may not contain dots")

    def test_the_repository_names_no_host_user_or_secret(self):
        banned = [re.compile(p) for p in (r"/home/[a-z]+", r"BEGIN [A-Z ]*PRIVATE KEY", r"github_pat_|ghp_[A-Za-z0-9]{20}")]
        for dirpath, dirnames, filenames in os.walk(ROOT):
            dirnames[:] = [d for d in dirnames if d not in (".git", "__pycache__")]
            for n in filenames:
                if n.endswith(".pyc") or dirpath.endswith(os.sep + "host") and n.endswith(".py"):
                    continue
                if n in ("test_manifest.py", "test_keys.py"):  # test_keys.py holds fake key headers as hostile input, test_manifest.py the patterns
                    continue
                with open(os.path.join(dirpath, n), "r", errors="replace") as f:
                    body = f.read()
                for rx in banned:
                    self.assertIsNone(rx.search(body), "%s matches %s" % (os.path.join(dirpath, n), rx.pattern))

    def test_the_readme_says_it_is_not_affiliated_and_names_the_licence(self):
        with open(os.path.join(ROOT, "README.md")) as f:
            readme = f.read()
        self.assertIn("not affiliated with, endorsed by or sponsored by herdr", readme)
        self.assertIn("Licence: Apache-2.0 ([LICENSE](LICENSE))", readme)
        with open(os.path.join(ROOT, "LICENSE")) as f:
            licence = f.read()
        self.assertIn("Apache License", licence)
        self.assertIn("Version 2.0, January 2004", licence)
        self.assertFalse(os.path.exists(os.path.join(ROOT, "LICENSE-PENDING.md")), "the licence is chosen: the placeholder is gone")


if __name__ == "__main__":
    unittest.main()
