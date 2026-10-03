#!/usr/bin/env python3
"""Fail when the host scripts this plugin ships differ from the Paddock app repository's pins.

  tools/check_pins.py [--app-repo PATH]          compare (default PATH: $PADDOCK_APP_REPO, else ../paddock-android)
  tools/check_pins.py [--app-repo PATH] --sync   copy the two scripts from the app repository and rewrite host/SOURCE.json

The hashes live in two places (the app's host/SOURCE.json and this repository's mirror of it), and the scripts in two more (the
app's host/ and this one's), so a release must show all four agree. The app refuses a script whose hash it does not know, so a
plugin that ships an older or newer script than the app pins would be found, refused and useless on the phone.
"""
import argparse
import hashlib
import json
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = ("relay", "control")  # the keys in host/SOURCE.json whose values are file names
VERSION_KEYS = {"relay": "version", "control": "control_version"}


def sha(path):
    with open(path, "rb") as f:
        return "sha256:" + hashlib.sha256(f.read()).hexdigest()


def load(path):
    with open(path) as f:
        return json.load(f)


def manifest_version(root):
    with open(os.path.join(root, "herdr-plugin.toml")) as f:
        for line in f:
            if line.startswith("version"):
                return line.split("=", 1)[1].strip().strip('"')
    return None


def check(root, app_repo):
    """Returns (rows, failures): one (what, ok, detail) row per comparison."""
    rows = []

    def row(what, ok, detail=""):
        rows.append((what, ok, detail))

    mirror = load(os.path.join(root, "host", "SOURCE.json"))
    app = load(os.path.join(app_repo, "host", "SOURCE.json"))
    row("manifest version equals the mirror's plugin_version", manifest_version(root) == mirror.get("plugin_version"),
        "manifest %s, mirror %s" % (manifest_version(root), mirror.get("plugin_version")))
    shipped = set()
    for key in SCRIPTS:
        name = mirror.get(key)
        row("%s: script name equals the app's" % key, name is not None and name == app.get(key), "plugin %s, app %s" % (name, app.get(key)))
        vk = VERSION_KEYS[key]
        row("%s: version equals the app's" % key, mirror.get(vk) is not None and mirror.get(vk) == app.get(vk), "plugin %s, app %s" % (mirror.get(vk), app.get(vk)))
        rel = "host/%s" % name
        shipped.add(rel)
        pin_app = app.get("files", {}).get(rel)
        pin_mirror = mirror.get("files", {}).get(rel)
        file_here = os.path.join(root, rel)
        actual = sha(file_here) if os.path.isfile(file_here) else None
        row("%s: the app pins it" % name, pin_app is not None)
        row("%s: the mirror equals the app's pin" % name, pin_mirror is not None and pin_mirror == pin_app, "mirror %s, app %s" % (pin_mirror, pin_app))
        row("%s: the shipped file hashes to the pin" % name, actual is not None and actual == pin_app, "file %s, pin %s" % (actual, pin_app))
        file_app = os.path.join(app_repo, rel)
        if os.path.isfile(file_app):
            with open(file_here, "rb") as a, open(file_app, "rb") as b:
                same = a.read() == b.read() if actual else False
            row("%s: byte-identical to the app repository's copy" % name, same)
    extra = sorted(
        "host/" + n for n in os.listdir(os.path.join(root, "host")) if n != "SOURCE.json" and "host/" + n not in shipped and not n.startswith(".") and n != "__pycache__"
    )
    row("no unpinned script is shipped", not extra, ", ".join(extra))
    row("the mirror lists exactly the shipped scripts", sorted(mirror.get("files", {})) == sorted(shipped), "mirror %s" % sorted(mirror.get("files", {})))
    return rows, [r for r in rows if not r[1]]


def sync(root, app_repo):
    app = load(os.path.join(app_repo, "host", "SOURCE.json"))
    mirror = load(os.path.join(root, "host", "SOURCE.json"))
    files = {}
    for key in SCRIPTS:
        name = app[key]
        shutil.copyfile(os.path.join(app_repo, "host", name), os.path.join(root, "host", name))
        files["host/" + name] = app["files"]["host/" + name]
        mirror[key] = name
        mirror[VERSION_KEYS[key]] = app[VERSION_KEYS[key]]
    mirror["files"] = dict(sorted(files.items()))
    with open(os.path.join(root, "host", "SOURCE.json"), "w") as f:
        json.dump(mirror, f, indent=2)
        f.write("\n")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--app-repo", default=os.environ.get("PADDOCK_APP_REPO") or os.path.join(os.path.dirname(ROOT), "paddock-android"))
    ap.add_argument("--root", default=ROOT, help="the plugin repository (default: this one; tests pass a copy)")
    ap.add_argument("--sync", action="store_true")
    args = ap.parse_args(argv)
    if not os.path.isfile(os.path.join(args.app_repo, "host", "SOURCE.json")):
        sys.stderr.write("no host/SOURCE.json under %s: pass --app-repo or set PADDOCK_APP_REPO\n" % args.app_repo)
        return 2
    if args.sync:
        sync(args.root, args.app_repo)
        print("copied the scripts and rewrote host/SOURCE.json from %s" % args.app_repo)
    rows, failures = check(args.root, args.app_repo)
    for what, ok, detail in rows:
        print("%s  %s%s" % ("PASS" if ok else "FAIL", what, "" if ok or not detail else "  (" + detail + ")"))
    print("%d checks, %d failed" % (len(rows), len(failures)))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
