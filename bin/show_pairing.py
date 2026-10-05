#!/usr/bin/env python3
"""show-pairing: print the paddock://pair link for this machine: host, port, user, herdr session and the SSH host-key fingerprints.

The link holds no key and no secret. Open it on the phone: Paddock fills in Add a machine and, at the first connection, compares
the fingerprint the server presents with the ones named here. The user still taps Trust. In a herdr popup it asks which host
name the phone should use (Enter keeps the default); for scripts and tests every field has an argument.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
import paddock_plugin as pp  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description="Print the Paddock pairing link for this machine.")
    ap.add_argument("--host", help="the name or address the phone connects to (default: this machine's hostname)")
    ap.add_argument("--port", type=int, help="the SSH port (default: sshd_config's first Port, else 22)")
    ap.add_argument("--user", help="the SSH user (default: the user running herdr)")
    ap.add_argument("--session", help="the herdr session name (default: the session this runs in; none for the default session)")
    ap.add_argument("--ssh-dir", default="/etc/ssh", help="where the ssh_host_*_key.pub files are (default /etc/ssh)")
    ap.add_argument("--no-prompt", action="store_true", help="never ask; use the defaults and the arguments")
    ap.add_argument("--no-qr", action="store_true", help="do not draw a QR code even when qrencode is installed")
    args = ap.parse_args(argv)
    interactive = not args.no_prompt and sys.stdin.isatty() and sys.stdout.isatty()
    out = sys.stdout
    try:
        prints = pp.read_host_key_fingerprints(args.ssh_dir)
        if not prints:
            raise pp.Refusal("No readable SSH host key files were found in %s, so there is nothing for the phone to check. "
                             "A pairing link without a fingerprint is not made." % args.ssh_dir, 3)
        host = args.host or pp.default_host()
        if interactive and not args.host:
            host = pp.prompt_host(host, sys.stdin, out)
        port = args.port if args.port is not None else pp.sshd_port()
        user = args.user or pp.current_user()
        session = args.session if args.session is not None else pp.herdr_session(os.environ)
        note = None
        if session is not None and not pp.SESSION_RE.match(session):
            note = "The herdr session name is not one Paddock accepts, so the link names no session."
            session = None
        link = pp.build_link(host, port, user, [f for _, _, f in prints], session)
    except pp.Refusal as r:
        sys.stderr.write(r.message + "\n") if not interactive else out.write("\n" + r.message + "\n")
        if interactive:
            pp.pause()
        return r.code
    out.write("Paddock pairing link. It holds no key and no secret, only public host-key fingerprints.\n\n%s\n\n" % link)
    out.write("  host     %s   (the phone must be able to reach this name or address; change it with --host)\n" % host)
    out.write("  port     %d\n  user     %s\n  session  %s\n" % (port, user, session or "(the default herdr session)"))
    out.write("  host keys the phone will accept:\n")
    for name, _, fp in prints:
        out.write("    %-12s %s\n" % (name, fp))
    if note:
        out.write("  note     %s\n" % note)
    out.write("\nOpen the link on the phone (share it to Paddock, or paste it into Add a machine). Paddock fills in the machine and, at the\n"
              "first connection, shows the fingerprint the server presents next to these. Tap Trust only if they match; a fingerprint that\n"
              "is not in the link is refused.\n")
    qr = None if args.no_qr else pp.draw_qr(link)
    if qr is not None:
        out.write("\n" + qr)
    if interactive:
        pp.pause()
    return 0


if __name__ == "__main__":
    sys.exit(main())
