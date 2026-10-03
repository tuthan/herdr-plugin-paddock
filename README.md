# Paddock for herdr: the host plugin

Paddock is an independent Android app that watches and answers the agents in your [herdr](https://herdr.dev) sessions over SSH.
**It is not affiliated with, endorsed by or sponsored by herdr or its authors.** This plugin is the small host-side half of
setting a phone up: it makes enrolling a phone one step instead of several, and it ships the two host scripts the app uses.

Status: 0.1.0, not yet published. The licence is not chosen yet (see [LICENSE-PENDING.md](LICENSE-PENDING.md)); nothing here may
be reused until it is.

## Install

```sh
herdr plugin install <owner>/herdr-plugin-paddock --ref v0.1.0
```

`<owner>` is a placeholder until the repository is published. Run it in an interactive terminal: herdr shows a preview of the
plugin and its commands and asks before it installs (without a terminal it refuses unless you pass `--yes`). Read
`herdr-plugin.toml` and `bin/` first; they are short. This plugin has no build step and no startup or event hooks, so nothing
runs unless you choose an action. Needs herdr 0.9.1 or newer and Python 3.8 or newer. For development:
`herdr plugin link /path/to/herdr-plugin-paddock`.

## What it does

Two actions, each opening a small popup (herdr actions have no terminal, so the action opens the pane that has one):

- **Paddock: authorize a phone** (`paddock.authorize-phone`). Paste the one line Paddock copies under "Public key to authorize".
  The line is checked, then appended to `~/.ssh/authorized_keys`, once. What you paste is not shown on screen.
- **Paddock: show the pairing link** (`paddock.show-pairing`). Prints a `paddock://pair?...` link holding this machine's host name,
  SSH port, user, herdr session and the SSH host-key fingerprints, and a QR code of it when `qrencode` is installed. Open the link
  on the phone: Paddock fills in Add a machine and, at the first connection, shows the fingerprint the server presents next to the
  ones in the link. You still tap Trust, and a fingerprint that is not in the link is refused.

Run one from a pane in the herdr session you want, with `herdr plugin action invoke authorize-phone --plugin paddock` (the popup
opens on the herdr screen, so someone has to be attached to type into it), or bind a key in `config.toml`:

```toml
[[keys.command]]
key = "prefix+p"
type = "plugin_action"
command = "paddock.authorize-phone"
description = "authorize a phone for Paddock"
```

Both programs also run on their own, which is how the tests drive them:
`python3 bin/authorize_phone.py --stdin < keyline`, `python3 bin/show_pairing.py --no-prompt --host box.example.net`.

## What it will and will not write

The only thing this plugin ever writes to `authorized_keys` is one validated phone key line, appended once. Specifically:

- The input must be exactly one line (one trailing line break is fine): `ecdsa-sha2-nistp256 <base64> [comment]`, single
  spaces, no options in front (`command=`, `from=`, ...), no other key type, and a key part that decodes to a P-256 public key.
  The comment is optional, up to 64 characters from `A-Za-z0-9@._-`. At most 1024 bytes are read.
- Anything that looks like a private key is refused. Refusals never repeat what was pasted.
- `~/.ssh` is created with mode 700 and the file with 600 when missing, and both are set to those modes. A newline is added
  first only when the file is not empty and does not end in one. Every other byte of the file is left as it was: the line is
  appended in one write, never by rewriting the file. A line that is already there (exact match) is not added twice.
- It refuses, and changes nothing, when `~/.ssh` or `authorized_keys` is a symbolic link, is not a plain directory or file, or is
  writable by group or others.

The pairing link carries no key and no secret. It names the public host-key fingerprints from `/etc/ssh/ssh_host_*_key.pub`
(ED25519, ECDSA, RSA; at most four). If none can be read, no link is made.

## The host scripts

`host/paddock-relay.py` and `host/paddock-control.py` are byte-identical copies of the scripts the Paddock app pins, with their
hashes in `host/SOURCE.json`. The app verifies the sha256 before it uses either, wherever it found it. `tools/check_pins.py`
compares them, the mirror and the app repository's own pins, and fails on any difference; `--sync` copies from the app repository.
The plugin never runs them itself.

## Tests

```sh
python3 -m unittest discover -s tests -v
python3 tools/check_pins.py --app-repo /path/to/paddock-android
```

## Privacy

No analytics, no network access, no files read or written outside `~/.ssh/authorized_keys` (written), `/etc/ssh` host key and
`sshd_config` files (read) and the herdr plugin directories. The repository holds no secret, key, host name or address.
