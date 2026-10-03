#!/usr/bin/env python3
"""authorize-phone: add the phone's public key line to ~/.ssh/authorized_keys, and nothing else.

In a herdr popup (no arguments, a terminal): asks for one pasted line with echo off. For scripts and tests: `--stdin`.
What it will and will not write is in the README; the rules are in lib/paddock_plugin.py.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
import paddock_plugin as pp  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description="Authorize a phone's Paddock key for SSH logins to this user.")
    ap.add_argument("--stdin", action="store_true", help="read the key line from standard input (no prompt, no waiting)")
    ap.add_argument("--home", help="change this home directory's .ssh instead of the current user's (for tests)")
    args = ap.parse_args(argv)
    home = args.home or os.path.expanduser("~")
    interactive = not args.stdin and sys.stdin.isatty()
    try:
        if args.stdin:
            data = sys.stdin.buffer.read(pp.MAX_INPUT_BYTES + 2)
        elif interactive:
            sys.stdout.write("Paddock: authorize a phone\n\n"
                             "In Paddock, open Add a machine and press Copy under \"Public key to authorize\", then paste that\n"
                             "one line here and press Enter. What you paste is not shown. Only a " + pp.KEY_TYPE + " line is\n"
                             "accepted; nothing else is ever written to authorized_keys.\n\n")
            data = pp.read_line("Key line: ", hidden=True)
        else:
            raise pp.Refusal("There is no terminal to ask in. Run this from the herdr action, or pipe the key line in with --stdin.")
        key = pp.parse_key_line(data)
        result = pp.authorize(home, key)
    except pp.Refusal as r:
        sys.stderr.write(r.message + "\n") if not interactive else sys.stdout.write("\n" + r.message + "\n")
        if interactive:
            pp.pause()
        return r.code
    if result.status == "added":
        msg = "Authorized this phone key:\n  %s\nAdded one line to %s (mode 600). Nothing else in the file was changed.\n" % (result.fingerprint, result.path)
    else:
        msg = "This phone key is already authorized:\n  %s\n%s was not changed.\n" % (result.fingerprint, result.path)
    sys.stdout.write(("\n" if interactive else "") + msg)
    if interactive:
        sys.stdout.write("Compare the fingerprint with the one Paddock shows, then connect from the phone.\n")
        pp.pause()
    return 0


if __name__ == "__main__":
    sys.exit(main())
