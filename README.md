# Paddock for herdr: the host plugin

Paddock is an independent Android app that watches and answers the agents in your [herdr](https://herdr.dev) sessions over SSH.
**It is not affiliated with, endorsed by or sponsored by herdr or its authors.** This plugin is the small host-side half of
setting a phone up: it makes enrolling a phone one step instead of several, and it ships the two host scripts the app uses.

Status: 0.2.0, on GitHub but not yet tagged or listed in the herdr marketplace. Licence: Apache-2.0 ([LICENSE](LICENSE)), the same as the Paddock app.

## Install

```sh
herdr plugin install tuthan/herdr-plugin-paddock
```

That installs the default branch. Releases will be tagged `v<version>` and installed with `--ref v<version>`; none is tagged yet. Run it in an interactive terminal: herdr shows a preview of the
plugin and its commands and asks before it installs (without a terminal it refuses unless you pass `--yes`). Read
`herdr-plugin.toml` and `bin/` first; they are short. This plugin has no build step and no startup or event hooks, so nothing
runs unless you choose an action. Needs herdr 0.9.1 or newer and Python 3.8 or newer, on Linux or macOS (see Platforms). For development:
`herdr plugin link /path/to/herdr-plugin-paddock`.

## Platforms

Linux and macOS (`platforms = ["linux", "macos"]` in the manifest). The Linux paths are the ones run for real: the live check against a disposable
herdr session, and a phone. **The macOS paths have not been run on a Mac.** They are unit-tested (`tests/test_macos.py`) against stand-ins that print
what `route`, `ipconfig`, `ifconfig`, `pbcopy` and `socketfilterfw` print, and the two host scripts use only POSIX calls. On macOS:

- Turn on **Remote Login** (System Settings > General > Sharing), or the phone has nothing to connect to. Host keys are read from `/etc/ssh` and the
  key goes to `~/.ssh/authorized_keys`, as on Linux.
- The popup's default host is the default route's address, from `route -n get default` and `ipconfig getifaddr <interface>`. With a VPN as the default
  route (no LAN address) it falls back to the host name, which a phone usually cannot resolve: pass `--host` with the address.
- `c` + Enter copies the link with `pbcopy`. `qrencode` for the QR is `brew install qrencode`.
- **There is no camera intake**: it reads a V4L2 camera with `zbarcam`, and macOS has neither. Paste the key line or use the listener; the popup says so.
- If the macOS firewall is on, the popup says so under the listening line: click Allow when macOS asks whether Python may accept incoming network
  connections. The plugin reads the firewall's state and changes nothing in it.

## What it does

Three actions, each opening a small popup (herdr actions have no terminal, so the action opens the pane that has one):

- **Paddock: authorize a phone** (`tuthan.paddock.authorize-phone`). Paste the one line Paddock copies under "Public key to authorize".
  The line is checked, then appended to `~/.ssh/authorized_keys`, once. What you paste is not shown on screen.
- **Paddock: show the pairing link** (`tuthan.paddock.show-pairing`). Prints a `paddock://pair?...` link holding this machine's LAN address (its host name only when it has none: a phone almost never resolves the host name),
  SSH port, user, herdr session and the SSH host-key fingerprints, and a QR code of it when `qrencode` is installed. Open the link
  on the phone: Paddock fills in Add a machine and, at the first connection, shows the fingerprint the server presents next to the
  ones in the link. You still tap Trust, and a fingerprint that is not in the link is refused.
- **Paddock: pair a phone** (`tuthan.paddock.pair`). The one-popup version of the two above: it shows the pairing link and its QR, takes the
  phone's public key from whichever of three intakes answers first, shows the key's fingerprint, and writes `authorized_keys` only
  after you approve. See "Pair a phone" below.

Run one from a pane in the herdr session you want, with `herdr plugin action invoke authorize-phone --plugin tuthan.paddock` (the popup
opens on the herdr screen, so someone has to be attached to type into it), or bind a key in `config.toml`:

```toml
[[keys.command]]
key = "prefix+p"
type = "plugin_action"
command = "tuthan.paddock.authorize-phone"
description = "authorize a phone for Paddock"
```

The programs also run on their own, which is how the tests drive them:
`python3 bin/authorize_phone.py --stdin < keyline`, `python3 bin/show_pairing.py --no-prompt --host box.example.net`,
`printf '%s\na\n' "$keyline" | python3 bin/pair.py --stdin --no-listen --no-camera --home /tmp/h` (the key line, then the answer).


### Open it with one key

herdr 0.9.1 has no menu or command palette for plugin actions; a plugin action is run by a key binding or `herdr plugin action invoke`. Bind one key in
`~/.config/herdr/config.toml` (then reload with your reload key, `prefix+q` by default) and `prefix+?` lists it:

```toml
[[keys.command]]
key = "prefix+alt+p"
type = "plugin_action"
command = "tuthan.paddock.pair"
description = "Paddock: pair a phone"
```

## Pair a phone

`tuthan.paddock.pair` opens one popup that does the whole enrollment. It prints the pairing link and, when `qrencode` is installed, its QR.
Then it waits (120 seconds by default, `--timeout`) for **one** complete key line from whichever intake answers first, and closes
the others:

- **The phone's listener.** In Add a machine, the app's **Send the key** control sends its public key to the address and port
  the link names. The popup opens a TCP listener on this machine's LAN address and a random port, and the link carries that port and
  a session handle (`&pair=<port>&sid=<handle>`). It is LAN-only (it refuses a public address and `0.0.0.0`), optional
  (`--no-listen`, or `--listen-ip ADDRESS` to choose the address), holds one key, replies with one word (`pending`, `ok`, `rejected`,
  `expired`, `refused`, `busy` or `none`) and is closed when the popup is. The channel is plaintext on purpose: what it carries is a
  public key and a session handle, nothing secret, and the protection is the fingerprint comparison below. It never sends the phone
  a credential, a file or any fact about this machine. The wire is in [PROTOCOL.md](PROTOCOL.md).
- **The webcam.** The phone shows its key as a QR (**Show as QR**) and `zbarcam --raw --oneshot --nodisplay --prescale=640x480
  <device>` reads it. **The camera is not used until you press Enter in the popup**, which says so beforehand; it is switched off
  as soon as a code is read, another intake answers, the time is up or the popup is closed. It reads `/dev/video0` unless
  `--camera-device PATH` says otherwise; `--no-camera` removes the intake. Without `zbarcam` (the `zbar` package) or a camera the
  popup says the intake is absent.
- **Paste.** As in authorize-phone: paste the key line and press Enter. Echo is off, so the line is never drawn.
- **A firewall on this machine.** The listener's port is random, and a firewall that denies incoming connections (ufw and firewalld by default) drops the
  phone's connection without an answer: the phone only says it cannot reach the machine (ufw logs `UFW BLOCK ... DPT=<port>`). When ufw or firewalld is
  active the popup says so under the listening line and prints the command that opens that port for this pairing (`sudo ufw allow proto tcp from <network>
  to any port <port>`; firewalld: `sudo firewall-cmd --add-port=<port>/tcp`, gone at the next reload) and the one that closes it. The plugin runs neither.
- **Copy the link.** Type `c` and press Enter (it is not a key, and it is only taken while the popup waits for one): the pairing link, with no key and no
  secret in it, goes to the desktop clipboard through `wl-copy` (Wayland), `xclip` or `xsel`, whichever the session has; with none of them the popup asks
  the terminal to copy it (OSC 52) and says that is a request. A herdr popup is not a pane, so herdr's mouse selection and copy-on-select do not work in it (they do in a normal pane: run `python3 bin/show_pairing.py --no-qr` from the plugin directory in a shell there; that link has no listener, so the phone pastes or scans it but cannot Send the key); the terminal's own Shift+drag selects raw screen text, other panes' included.
  The QR is drawn with a 2-module light border (`qrencode -m 2`); a phone camera reads a code from a screen only from about 4 pixels a module, so hold the
  phone close or make the terminal font larger.

Whatever arrives is checked exactly as `authorize-phone` checks a pasted line (one `ecdsa-sha2-nistp256` line, no options, no private
keys, at most 1024 bytes). A refusal is explained without repeating what was received, and nothing is written. A second, different
key is ignored (the listener answers it `busy`). A refusal ends the run, and a phone's key that arrives after it is answered `expired`.

**Approving.** The popup shows the key's SHA-256 fingerprint with its first eight characters set off, and asks `[R]eject (default) /
[a]pprove`. Compare it with the fingerprint the phone shows. Only an `a` and Enter approves; an empty line, any other answer, the end
of input or the time running out is Reject, and nothing is written. On approval the same function `authorize-phone` uses appends the
line to `~/.ssh/authorized_keys`, and the popup prints the file and the fingerprint and tells you to press Connect on the phone. There
is no code to type because SSH already pins this host's identity (the link names its host-key fingerprints) and what is delivered is
the phone's public key; the one attack left is another key being put in its place, and the fingerprint comparison catches it.

**What it never runs.** No shell, no command from the phone, nothing that is received is ever executed or written anywhere but
`authorized_keys`, and then only the validated line after your approval. The camera and the listener are the only things it opens, and
only for the time and in the way described here. No key material is printed or logged: only the fingerprint.

Options (for scripts and tests; the popup takes none): `--timeout SECONDS`, `--no-qr`, `--no-camera`, `--camera-device PATH`,
`--camera-now` (switch the camera on at once), `--no-listen`, `--listen-ip ADDRESS`, `--stdin` (the key line, then the answer, from
standard input; the listener opens only with `--listen-ip`), `--ssh-dir`, `--host`, `--port`, `--user`, `--home`. The exit code is 0
when a key was written (or was already there), 1 for Reject or no key in time, 2 for a refused key or bad option, 3 or 4 when
`authorize` refuses or fails.

## What it will and will not write

The only thing this plugin ever writes to `authorized_keys` is one validated phone key line, appended once. Specifically:

- The input must be exactly one line (one trailing line break is fine): `ecdsa-sha2-nistp256 <base64> [comment]`, single
  spaces, no options in front (`command=`, `from=`, ...), no other key type, and a key part that is canonical base64 (it re-encodes to the same text) of a P-256 public key.
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

No analytics, no outgoing network connections, no files read or written outside `~/.ssh/authorized_keys` (written), `/etc/ssh` host
key and `sshd_config` files (read) and the herdr plugin directories. The one thing that touches the network is the `pair` popup's
listener, and only while that popup is open: LAN-only, optional (`--no-listen`), plaintext, and it carries only a public key and a
session handle in, and one result word out. The webcam is read only after you press Enter in that popup. The repository holds no
secret, key, host name or address.
