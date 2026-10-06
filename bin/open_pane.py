#!/usr/bin/env python3
"""The herdr action's command: open this plugin's popup for `authorize-phone`, `show-pairing` or `pair`.

A herdr action has no terminal and no standard input (S1 in the Paddock evidence), so it cannot ask for a pasted line itself.
It opens the plugin pane of the same name, which does. Extra arguments go to `herdr plugin pane open` unchanged (for example
`--placement split`).
"""
import json
import os
import subprocess
import sys

ENTRYPOINTS = ("authorize-phone", "show-pairing", "pair")


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] not in ENTRYPOINTS:
        sys.stderr.write("usage: open_pane.py {%s} [herdr plugin pane open options]\n" % "|".join(ENTRYPOINTS))
        return 2
    herdr = os.environ.get("HERDR_BIN_PATH") or "herdr"
    plugin = os.environ.get("HERDR_PLUGIN_ID") or "tuthan.paddock"
    cmd = [herdr, "plugin", "pane", "open", "--plugin", plugin, "--entrypoint", argv[0]] + argv[1:]
    try:
        r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20)
    except (OSError, subprocess.SubprocessError) as e:
        sys.stderr.write("could not run herdr: %s\n" % e.__class__.__name__)
        return 1
    text = r.stdout.decode("utf-8", "replace").strip()
    try:
        error = json.loads(text).get("error")
    except ValueError:
        error = None
    if error:
        sys.stderr.write("herdr could not open the popup: %s (%s)\n" % (error.get("message", "no message"), error.get("code", "no code")))
        return 1
    if r.returncode != 0:
        sys.stderr.write(r.stderr.decode("utf-8", "replace")[:500])
        return r.returncode
    sys.stdout.write("opened %s\n" % argv[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
