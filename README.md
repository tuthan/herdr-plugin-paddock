# Paddock for herdr: the host plugin

Paddock is an independent Android app that watches and answers the agents in your [herdr](https://herdr.dev) sessions over SSH.
**It is not affiliated with, endorsed by or sponsored by herdr or its authors.** This plugin is the host-side half: it pairs a phone to this
machine from one popup, and ships the two host scripts the app uses.

Status: 0.2.0, on GitHub but not yet tagged or listed in the herdr marketplace. The Android app is in testing and not published yet (see the
[product page](https://tuthan.github.io/herdr-plugin-paddock/)). Licence: Apache-2.0 ([LICENSE](LICENSE)), the same as the Paddock app.

## Pair your phone

About two minutes. Do steps 1 and 2 once; after that, pairing a phone is steps 3 to 7.

### Before you start

- **The computer** runs herdr 0.9.1 or newer and Python 3.8 or newer (Linux or macOS).
- **An SSH server is running on it.** The phone connects to it after pairing, and the plugin does not start one.
  Linux: `sudo systemctl enable --now sshd` (the unit is `ssh` on Debian and Ubuntu). macOS: System Settings > General > Sharing > Remote Login.
- **The phone and the computer are on the same Wi-Fi or network** for the pairing. Guest networks that isolate devices from each other will not work.
  Afterwards a VPN such as Tailscale lets the phone connect from anywhere.
- **`qrencode`** is installed, so the popup can draw its QR code: `sudo pacman -S qrencode`, `sudo apt install qrencode` or `brew install qrencode`.
  Without it you open or paste the link on the phone instead of scanning it.
- **The Paddock app** is on the phone.

### 1. Install the plugin

On the computer that runs herdr, in a terminal:

```sh
herdr plugin install tuthan/herdr-plugin-paddock
```

herdr shows what the plugin contains and asks before it installs. Read `herdr-plugin.toml` and `bin/` first if you like; they are short. The
plugin has no build step and no startup or event hooks, so nothing runs unless you choose an action. (For development:
`herdr plugin link /path/to/herdr-plugin-paddock`.)

### 2. Pick how you will open the popup

Either run this from a pane in the herdr session you want the phone to use, **with herdr open on your screen** (the popup appears there):

```sh
herdr plugin action invoke pair --plugin tuthan.paddock
```

or bind a key once in `~/.config/herdr/config.toml`, reload herdr (`prefix+q` by default), and press it any time; `prefix+?` lists it:

```toml
[[keys.command]]
key = "prefix+alt+p"
type = "plugin_action"
command = "tuthan.paddock.pair"
description = "Paddock: pair a phone"
```

### 3. Open the pairing popup

Run the command or press the key. The popup first asks **"Host name or address the phone should use"** and shows this machine's LAN address
in brackets: press Enter to accept it, or type another address (for example a Tailscale one). Then it shows a QR code and starts waiting
for 120 seconds.

### 4. Scan it with the phone

In Paddock, tap **Scan the code on the desktop** and point the camera at the QR in the popup. **Add a machine** fills in the address, port,
user, herdr session and this machine's SSH fingerprints. (No camera or no `qrencode`? Open the `paddock://` link on the phone instead; type
`c` and Enter in the popup to copy it.)

### 5. Send the phone's key

On the same screen, tap **Create this phone's key** if the phone has none yet, then **Send the key to ...** under it.

### 6. Compare, then approve

The popup says a key arrived and shows its fingerprint, with the first eight characters in brackets. The phone shows its **Key fingerprint** on
the same screen. If they match, type `a` and press Enter. **Anything else rejects**: Enter alone, any other letter, no answer before the time runs out.
A rejection writes nothing.

On approval the popup adds one line to `~/.ssh/authorized_keys` and says so.

### 7. Connect

On the phone, tap **Connect**. The first time, Paddock shows the machine's fingerprint and **"Same as the fingerprint in the pairing link"**: tap
**Trust and connect**. A fingerprint that is not in the link is refused.

Done. To unpair a phone, delete its line from `~/.ssh/authorized_keys`.

### If it does not work

| What you see | What to do |
|---|---|
| The phone says it cannot reach the machine | Check, in order: **1)** same network, not a guest network; **2)** a firewall: when ufw or firewalld is running the popup prints, under "listening on", the command that opens the pairing port and the one that closes it again. Run the first in another terminal. **3)** the address: if it is wrong (a VPN, Docker or a host name the phone cannot resolve), run the popup again and type the right one at the first prompt; **4)** the SSH server is running (Before you start). |
| No QR code in the popup | Install `qrencode` and open the popup again, or type `c` and Enter to copy the link. |
| The popup says "No key arrived within 120 seconds" | Nothing was written. Open the popup again and go to step 4. |
| The popup says "No readable SSH host key files" | There is no SSH server's host key to check against. Install and start one (Before you start). |
| The two fingerprints differ | Press Enter to reject. Nothing is written. A key other than this phone's arrived (or you are looking at another phone's screen); pair again. |
| Paddock says the address "is not the machine in the pairing link" | It trusted nothing and did not sign in. Either the link is for another machine, or something else answers at that address. Pair again; do not trust it. |
| No camera on the phone | Tap **Show as QR** instead and hold it to the computer's webcam (press Enter in the popup first), or tap **Copy key only** and paste the line into the popup. |

macOS notes (no camera intake, the firewall prompt) are under [Platforms](#platforms).

---

**Reference.** Everything above is enough to pair. The rest is what each part does, for when you want to know, script it or audit it.

## The three actions

Each opens a small popup (herdr actions have no terminal, so the action opens the pane that has one). herdr 0.9.1 has no menu for plugin
actions: run one with `herdr plugin action invoke <id> --plugin tuthan.paddock` or bind a key as in step 2.

- **Paddock: pair a phone** (`pair`). The one-popup flow above: the link and its QR, the phone's key from whichever intake answers first, its
  fingerprint, and `authorized_keys` written only after you approve. See [Pair a phone](#pair-a-phone-in-detail).
- **Paddock: authorize a phone** (`authorize-phone`). Paste the one line Paddock copies under "Public key to authorize". The line is checked, then
  appended to `~/.ssh/authorized_keys`, once. What you paste is not shown on screen.
- **Paddock: show the pairing link** (`show-pairing`). Prints a `paddock://pair?...` link holding this machine's LAN address (its host name only when
  it has none: a phone almost never resolves the host name), SSH port, user, herdr session and the SSH host-key fingerprints, and a QR code of it when
  `qrencode` is installed. Open it on the phone: Paddock fills in Add a machine and, at the first connection, shows the fingerprint the server
  presents next to the ones in the link. You still tap Trust, and a fingerprint that is not in the link is refused.

The programs also run on their own, which is how the tests drive them:
`python3 bin/authorize_phone.py --stdin < keyline`, `python3 bin/show_pairing.py --no-prompt --host box.example.net`,
`printf '%s\na\n' "$keyline" | python3 bin/pair.py --stdin --no-listen --no-camera --home /tmp/h` (the key line, then the answer).

## Platforms

Linux and macOS (`platforms = ["linux", "macos"]` in the manifest). The Linux paths are the ones run for real: the live check against a disposable
herdr session, and a phone. **The macOS paths have not been run on a Mac.** They are unit-tested (`tests/test_macos.py`) against stand-ins that print
what `route`, `ipconfig`, `ifconfig`, `pbcopy` and `socketfilterfw` print, and the two host scripts use only POSIX calls. On macOS:

- Turn on **Remote Login** (System Settings > General > Sharing), or the phone has nothing to connect to. Host keys are read from `/etc/ssh` and the
  key goes to `~/.ssh/authorized_keys`, as on Linux.
- The popup's default host is the default route's address, from `route -n get default` and `ipconfig getifaddr <interface>`. With a VPN as the default
  route (no LAN address) it falls back to the host name, which a phone usually cannot resolve: type the address at the popup's first prompt (or pass `--host`).
- `c` + Enter copies the link with `pbcopy`. `qrencode` for the QR is `brew install qrencode`.
- **There is no camera intake**: it reads a V4L2 camera with `zbarcam`, and macOS has neither. Paste the key line or use the listener; the popup says so.
- If the macOS firewall is on, the popup says so under the listening line: click Allow when macOS asks whether Python may accept incoming network
  connections. The plugin reads the firewall's state and changes nothing in it.

## Pair a phone, in detail

`tuthan.paddock.pair` prints the pairing link and, when `qrencode` is installed, its QR. Then it waits (120 seconds by default, `--timeout`) for **one**
complete key line from whichever intake answers first, and closes the others:

- **The phone's listener** (the path in steps 4 to 6). The app's **Send the key** control sends its public key to the address and port the link names.
  The popup opens a TCP listener on this machine's LAN address and a random port, and the link carries that port and a session handle
  (`&pair=<port>&sid=<handle>`). It is LAN-only (it refuses a public address and `0.0.0.0`), optional (`--no-listen`, or `--listen-ip ADDRESS` to choose
  the address), holds one key, replies with one word (`pending`, `ok`, `rejected`, `expired`, `refused`, `busy` or `none`) and is closed when the popup is.
  The channel is plaintext on purpose: what it carries is a public key and a session handle, nothing secret, and the protection is the fingerprint
  comparison. It never sends the phone a credential, a file or any fact about this machine. The wire is in [PROTOCOL.md](PROTOCOL.md).
- **The webcam.** The phone shows its key as a QR (**Show as QR**) and `zbarcam --raw --oneshot --nodisplay --prescale=640x480 <device>` reads it.
  **The camera is not used until you press Enter in the popup**, which says so beforehand; it is switched off as soon as a code is read, another intake
  answers, the time is up or the popup is closed. It reads `/dev/video0` unless `--camera-device PATH` says otherwise; `--no-camera` removes the intake.
  Without `zbarcam` (the `zbar` package) or a camera the popup says the intake is absent.
- **Paste.** As in authorize-phone: paste the key line and press Enter. Echo is off, so the line is never drawn.

**A firewall on this machine.** The listener's port is random, and a firewall that denies incoming connections (ufw and firewalld by default) drops the
phone's connection without an answer: the phone only says it cannot reach the machine (ufw logs `UFW BLOCK ... DPT=<port>`). When ufw or firewalld is
active the popup says so under the listening line and prints the command that opens that port for this pairing (`sudo ufw allow proto tcp from <network>
to any port <port>`; firewalld: `sudo firewall-cmd --add-port=<port>/tcp`, gone at the next reload) and the one that closes it. The plugin runs neither.

**Copying the link.** Type `c` and press Enter (it is not a key, and it is only taken while the popup waits for one): the pairing link, with no key and no
secret in it, goes to the desktop clipboard through `wl-copy` (Wayland), `xclip` or `xsel`, whichever the session has; with none of them the popup asks
the terminal to copy it (OSC 52) and says that is a request. A herdr popup is not a pane, so herdr's mouse selection and copy-on-select do not work in it
(they do in a normal pane: run `python3 bin/show_pairing.py --no-qr` from the plugin directory in a shell there; that link has no listener, so the phone
pastes or scans it but cannot Send the key); the terminal's own Shift+drag selects raw screen text, other panes' included.

**Scanning the QR.** It is drawn with a 2-module light border (`qrencode -m 2`); a phone camera reads a code from a screen only from about 4 pixels a
module, so hold the phone close or make the terminal font larger.

**What is accepted.** Whatever arrives is checked exactly as `authorize-phone` checks a pasted line (one `ecdsa-sha2-nistp256` line, no options, no
private keys, at most 1024 bytes). A refusal is explained without repeating what was received, and nothing is written. A second, different key is ignored
(the listener answers it `busy`). A refusal ends the run, and a phone's key that arrives after it is answered `expired`.

**Approving.** The popup shows the key's SHA-256 fingerprint with its first eight characters set off, and asks `[R]eject (default) / [a]pprove`. Only an
`a` and Enter approves; an empty line, any other answer, the end of input or the time running out is Reject, and nothing is written. On approval the same
function `authorize-phone` uses appends the line to `~/.ssh/authorized_keys`, and the popup prints the file and the fingerprint and tells you to press
Connect on the phone. There is no code to type because SSH already pins this host's identity (the link names its host-key fingerprints) and what is
delivered is the phone's public key; the one attack left is another key being put in its place, and the fingerprint comparison catches it.

**What it never runs.** No shell, no command from the phone, nothing that is received is ever executed or written anywhere but `authorized_keys`, and
then only the validated line after your approval. The camera and the listener are the only things it opens, and only for the time and in the way
described here. No key material is printed or logged: only the fingerprint.

**Options** (for scripts and tests; the popup takes none): `--timeout SECONDS`, `--no-qr`, `--no-camera`, `--camera-device PATH`, `--camera-now` (switch
the camera on at once), `--no-listen`, `--listen-ip ADDRESS`, `--stdin` (the key line, then the answer, from standard input; the listener opens only with
`--listen-ip`), `--ssh-dir`, `--host`, `--port`, `--user`, `--home`. The exit code is 0 when a key was written (or was already there), 1 for Reject or no
key in time, 2 for a refused key or bad option, 3 or 4 when `authorize` refuses or fails.

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

## Website

`site/` is the product page, published at <https://tuthan.github.io/herdr-plugin-paddock/> by `.github/workflows/pages.yml` on
every push to `main` that changes it. It is static HTML, CSS and JavaScript with no build step; open `site/index.html` to view it
locally. The plugin never reads it.

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
secret, key, host name or address; the addresses and fingerprints on the website are made-up examples.
