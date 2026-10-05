# Paddock pairing wire protocol, `paddock-pair/1`

What the phone and the plugin's `pair` popup say to each other over the network. It is implemented by `PairListener` in
`lib/paddock_plugin.py` (the phone side is the app's own client); this file is the contract, and the tests in
`tests/test_pair_listener.py` check every rule below.

The channel is plain TCP and nothing on it is secret: the phone sends its **public** key line, a session handle (`sid`, taken
from the QR the popup shows) and gets back one result word. The protection is not the channel. It is the owner comparing the
key's SHA-256 fingerprint on the phone and in the popup and typing `a` there (see README, "Pair a phone"). Nothing but a result
word ever travels from the host to the phone.

## Transport

- TCP over IPv4. The phone connects to the `host` of the pairing link at the `pair` port the link names.
- One request per connection, one reply, then the connection is closed. The server sends its line, half-closes its side, reads
  and discards anything else the client sends, and drops the connection when the client closes or after 5 seconds.
- A request is **one line**, ASCII, terminated by `\n` (not `\r\n`), at most **4096 bytes including the `\n`**. The whole line
  must arrive within **5 seconds of connecting**; a connection that is idle or slow past that is closed with no reply. Bytes
  after the first `\n` are ignored.
- The server accepts at most **8 simultaneous connections**; a ninth is closed at once with no reply.

## Requests

```
request        = key-request / status-request
key-request    = "paddock-pair/1" SP "key" SP sid SP keyline LF
status-request = "paddock-pair/1" SP "status" SP sid LF
sid            = 22 ( ALPHA / DIGIT / "_" / "-" )
keyline        = "ecdsa-sha2-nistp256" SP base64 [ SP comment ]
```

- Fields are separated by single spaces. `keyline` is the **rest of the line** and contains spaces.
- `keyline` must pass exactly the check `authorize-phone` applies: one line, `ecdsa-sha2-nistp256` only with nothing in front
  (no `command=`, `from=`, ...), a key part that is canonical base64 (it re-encodes to exactly the text sent, so a spelling that only differs in the unused bits of its last character is refused, as OpenSSH refuses it) of a P-256 public key, an optional comment of up to 64 characters from
  `A-Za-z0-9@._-`, at most 1024 bytes, printable ASCII, and nothing that looks like a private key.
- `sid` is compared in constant time (`hmac.compare_digest` on the ASCII bytes).

## Replies

```
reply = "paddock-pair/1" SP word LF
word  = "pending" / "ok" / "rejected" / "expired" / "refused" / "busy" / "none"
```

| word | meaning |
| --- | --- |
| `pending` | the popup holds the key and the owner has not decided |
| `ok` | the owner approved and the key is written to `authorized_keys` (the key is written before this word is ever sent) |
| `rejected` | the owner rejected it, approved a different key, or the write to `authorized_keys` failed (nothing was written) |
| `expired` | the window ended before the owner decided, or a request arrived after the window |
| `refused` | wrong `sid`, malformed line, wrong or missing version token, oversize line, or a key line that fails the key check; nothing is stored |
| `busy` | another, different key is held; or the sender is over the rate limit (below) |
| `none` | `status` before any key has been received |

A reply never contains any part of the request.

## State machine

The popup holds **at most one key** for its whole run: `none` until a key is stored, then `pending`, then `ok` or `rejected`
(`expired` is not stored: it is what a `pending` key is read as once the window has ended). "The same key" means the same type
and blob; a different comment does not make a different key. The first line is the one that is written.

`key`, once the rate rule (below) has let it through and the checks that give `refused` have passed:

1. window ended: `expired` (nothing is stored);
2. no key held: store it, reply `pending`;
3. the same key is held: reply its current state (`pending`, `ok` or `rejected`), so repeating a send is always safe;
4. a different key is held, pending or decided: `busy`, nothing of it is stored.

`status` with the correct `sid` (a wrong one is `refused`, and counted):

- no key held: `none`;
- the held key is undecided: `pending`, or `expired` once the window has ended;
- decided: `ok` or `rejected`.

A key that arrives by another intake (camera or paste) before the phone's is held the same way, so a phone that then sends a
different key gets `busy` and one that sends the same key gets its state. The first complete valid key from any intake wins;
a phone whose key is not the one approved is told `rejected`.

## Window, and how long an answer stays available

- The window is **120 seconds** by default (`--timeout`), from the moment the popup builds its link. It covers waiting for a key
  and the owner's answer to the prompt: there is no approving after it.
- `ok` and `rejected` are answered to `status` (and to the same key sent again) for as long as the listener is open, so a phone
  that lost the reply can ask again. In the terminal popup that is until Enter closes the popup, or 10 seconds after the window
  ends, whichever comes first. In a script run (`--stdin`) it is until the phone has been told the final word once, for at
  most 6 seconds. The listener is also closed when the popup exits or is closed.

## Limits

- **Rate:** at most **12 counted requests per source address per rolling 60 seconds**. Counted are every `key` request (valid or
  not), every request with a wrong `sid`, and every malformed or oversize line. **Not counted: a `status` request with the
  correct `sid`**, so a phone polling every 2 seconds is never throttled, and a throttled address still gets real answers to its
  correct status polls. A counted request over the limit is answered `busy` without being looked at, and nothing is stored.
  (A phone sends one `key`, then polls `status`; it resends the key only when `status` says `none`, which is why only keys are
  counted.) At most 1024 source addresses are tracked; when the table is full, new addresses' counted requests get `busy`.
- **Size and time:** 4096 bytes and 5 seconds per request; 8 simultaneous connections (above).
- **Nothing is logged but the verb and the word** (`key -> pending`). Never the request, the key line or the address.

## Where it listens

- One IPv4 address and a random port (the OS picks it, a new one every run). The address is the one on the default route's
  device (`ip -json -4 route show default`, then `ip -json -4 addr show dev <dev>`), or the one given with `--listen-ip`.
- It is LAN-only: the listener refuses `0.0.0.0`, multicast, the broadcast address and any **public** address (it stays off and
  says why). Private, link-local, carrier-grade-NAT and loopback addresses are allowed (loopback is what the tests and the
  emulator harness use). With no address, or with `--no-listen`, there is no listener and the link carries no `pair` or `sid`.
- It is bound to that one address, but the phone connects to the link's `host`. The two must be the same machine address, so
  when `host` is a name the popup says that it must reach the listener's address, and what to pass as `--host` if it does not.

## The link

The pairing link gains two parameters, appended after `session` and only when a listener is up: `&pair=<port>&sid=<22 characters>`.
A phone that does not know them ignores them and pairs the old way. `sid` is a fresh 16 random bytes in base64url for every run
of the popup. It is a session handle, not a key: it names this run, and it is not a credential for anything else.

## Notes for clients

- Send `key` once. If the reply is lost, ask `status`: `none` means the key never arrived (send it again, it is safe), `pending`
  or a final word means it did.
- Poll `status` as often as is useful; every 2 seconds is fine. Stop on `ok`, `rejected`, `expired` or `refused`.
- `busy` after your own `key` means a different key is already held, or you sent more than 12 counted requests in a minute.
  A correct `status` is never `busy`.
- The window is the popup's, not the phone's: the phone's own countdown starts at its first send and can run later than the
  popup's. `expired` from the popup is final.
- A connection that cannot be made is not an answer: nothing was sent, and nothing can have arrived.
