"""The pairing listener, one rule at a time, over loopback only (127.0.0.1, ephemeral ports) and with an injected clock.

The clients here speak the wire grammar written in PROTOCOL.md; the listener is driven by its own selector, one poll at a time,
so no test needs a thread or a sleep.
"""
import base64
import selectors
import socket
import unittest
from unittest import mock

from support import GOOD_BODY, GOOD_LINE, OTHER_LINE
from test_keys import HOSTILE, MARK, non_canonical_bodies
import paddock_plugin as pp

V = "paddock-pair/1"
KEY = pp.parse_key_line(GOOD_LINE)
# a second, different key: the good key's blob with its last byte changed (the check is on shape, not on the curve)
_raw = bytearray(base64.b64decode(GOOD_BODY))
_raw[-1] ^= 1
OTHER_BODY = base64.b64encode(bytes(_raw)).decode()
OTHER_KEY_LINE = "ecdsa-sha2-nistp256 " + OTHER_BODY + " second@phone"


class FakeClock(object):
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class Rig(object):
    """A listener on 127.0.0.1 with a fake clock, and a way to send one request and read what comes back."""

    def __init__(self, **kwargs):
        self.clock = FakeClock()
        self.sid = pp.new_sid()
        kwargs.setdefault("rate_limit", 100000)  # most tests send dozens of requests from one address; the Limits tests use the real 12
        self.listener = pp.PairListener("127.0.0.1", self.sid, clock=self.clock, **kwargs)
        self.clients = []

    def close(self):
        for c in self.clients:
            c.close()
        self.listener.close()

    def connect(self, source=None):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if source:
            s.bind((source, 0))
        s.connect(("127.0.0.1", self.listener.port))
        s.setblocking(False)
        self.clients.append(s)
        return s

    def pump(self, rounds=3):
        for _ in range(rounds):
            self.listener.poll(0.002)

    def read(self, s, rounds=120):
        """Everything the server sends until it closes the connection, and whether it did. A reset counts as closed."""
        data = b""
        for _ in range(rounds):
            self.listener.poll(0.005)
            try:
                chunk = s.recv(4096)
            except BlockingIOError:
                continue
            except OSError:
                return data, True
            if not chunk:
                return data, True
            data += chunk
        return data, False

    def ask(self, payload, source=None):
        """Sends [payload] on a new connection and returns the one reply line (str, without its newline); the connection is then closed."""
        s = self.connect(source)
        s.sendall(payload)
        data, closed = self.read(s)
        s.close()
        self.clients.remove(s)
        self.pump()
        assert closed, "the server did not close the connection after its reply"
        assert data.endswith(b"\n") and data.count(b"\n") == 1, data
        text = data.decode("ascii")[:-1]
        assert text.startswith(V + " "), text
        return text[len(V) + 1:]

    def key(self, line=GOOD_LINE, sid=None):
        return self.ask(("%s key %s %s\n" % (V, sid or self.sid, line)).encode())

    def status(self, sid=None, source=None):
        return self.ask(("%s status %s\n" % (V, sid or self.sid)).encode(), source)


class ListenerCase(unittest.TestCase):
    def setUp(self):
        self.rig = Rig()
        self.addCleanup(self.rig.close)
        self.l = self.rig.listener
        self.clock = self.rig.clock


class Rules(ListenerCase):
    def test_a_status_before_any_key_is_none_and_the_reply_is_one_exact_line(self):
        s = self.rig.connect()
        s.sendall(("%s status %s\n" % (V, self.rig.sid)).encode())
        data, closed = self.rig.read(s)
        self.assertEqual(b"paddock-pair/1 none\n", data)
        self.assertTrue(closed)

    def test_a_key_is_stored_pending_and_status_says_so(self):
        self.assertEqual("pending", self.rig.key())
        self.assertEqual("pending", self.rig.status())
        self.assertEqual(GOOD_LINE, self.l.held.line)
        self.assertEqual("pending", self.l.state)

    def test_a_wrong_sid_is_refused_for_both_verbs_and_nothing_is_stored(self):
        other = pp.new_sid()
        self.assertNotEqual(other, self.rig.sid)
        self.assertEqual("refused", self.rig.key(sid=other))
        self.assertEqual("refused", self.rig.status(sid=other))
        self.assertIsNone(self.l.held)
        self.assertEqual("none", self.rig.status())

    def test_a_sid_of_the_wrong_shape_is_refused(self):
        flipped = self.rig.sid[:-1] + ("A" if self.rig.sid[-1] != "A" else "B")
        for sid in ("", "short", self.rig.sid[:-1], self.rig.sid + "A", self.rig.sid[:-1] + "!", flipped):
            with self.subTest(sid=sid):
                self.assertEqual("refused", self.rig.ask(("%s status %s\n" % (V, sid)).encode()))
                self.assertEqual("refused", self.rig.ask(("%s key %s %s\n" % (V, sid, GOOD_LINE)).encode()))
        self.assertIsNone(self.l.held)

    def test_the_sid_is_compared_with_hmac_compare_digest(self):
        with mock.patch.object(pp.hmac, "compare_digest", wraps=pp.hmac.compare_digest) as spy:
            self.rig.status()
            self.rig.key(sid=pp.new_sid())
        self.assertEqual(2, spy.call_count)
        for call in spy.call_args_list:
            self.assertTrue(all(isinstance(a, bytes) for a in call[0]))

    def test_malformed_lines_are_refused(self):
        sid = self.rig.sid
        for name, line in [
            ("an empty line", b""),
            ("garbage", b"hello"),
            ("the version only", V.encode()),
            ("key with nothing after it", ("%s key" % V).encode()),
            ("key with a sid and no line", ("%s key %s" % (V, sid)).encode()),
            ("key with a sid and a trailing space", ("%s key %s " % (V, sid)).encode()),
            ("status with nothing after it", ("%s status" % V).encode()),
            ("status with an extra word", ("%s status %s more" % (V, sid)).encode()),
            ("an unknown verb", ("%s hello %s" % (V, sid)).encode()),
            ("a verb in capitals", ("%s STATUS %s" % (V, sid)).encode()),
            ("a leading space", (" %s status %s" % (V, sid)).encode()),
            ("two spaces after the version", ("%s  status %s" % (V, sid)).encode()),
            ("a tab for a space", ("%s\tstatus %s" % (V, sid)).encode()),
            ("a trailing carriage return", ("%s status %s\r" % (V, sid)).encode()),
            ("a non-ASCII byte", ("%s status %s" % (V, sid)).encode() + b"\xff"),
            ("a NUL byte", ("%s status %s" % (V, sid)).encode() + b"\x00"),
            ("a key line with a carriage return", ("%s key %s %s\r" % (V, sid, GOOD_LINE)).encode()),
        ]:
            with self.subTest(name):
                self.assertEqual("refused", self.rig.ask(line + b"\n"))
        self.assertIsNone(self.l.held)

    def test_a_wrong_or_missing_version_token_is_refused(self):
        sid = self.rig.sid
        for name, version in [("version 2", "paddock-pair/2"), ("version 0", "paddock-pair/0"), ("no number", "paddock-pair"), ("another name", "paddock/1"),
                              ("capitals", "PADDOCK-PAIR/1"), ("a suffix", "paddock-pair/1x"), ("a prefix", "xpaddock-pair/1"), ("the sid in its place", sid)]:
            with self.subTest(name):
                self.assertEqual("refused", self.rig.ask(("%s status %s\n" % (version, sid)).encode()))
                self.assertEqual("refused", self.rig.ask(("%s key %s %s\n" % (version, sid, GOOD_LINE)).encode()))
        self.assertEqual("refused", self.rig.ask(("status %s\n" % sid).encode()), "no version token at all")
        self.assertIsNone(self.l.held)

    def test_a_key_line_that_fails_the_key_check_is_refused_and_nothing_is_stored(self):
        tried = 0
        for name, data, _ in HOSTILE:
            if "\n" in data or len(data) > 3000 or not data:
                continue  # a newline would end the request line; the long ones are the oversize test's
            tried += 1
            with self.subTest(name):
                reply = self.rig.ask(("%s key %s %s\n" % (V, self.rig.sid, data)).encode("utf-8", "surrogateescape"))
                self.assertEqual("refused", reply)
                self.assertNotIn(MARK, reply)
        self.assertGreater(tried, 35)
        self.assertIsNone(self.l.held)
        self.assertEqual("none", self.rig.status())

    def test_a_non_canonical_base64_key_is_refused_over_the_wire_and_nothing_is_stored(self):
        for body in non_canonical_bodies():
            with self.subTest(body=body[-4:]):
                self.assertEqual("refused", self.rig.key("ecdsa-sha2-nistp256 " + body + " paddock@phone"))
        self.assertIsNone(self.l.held)
        self.assertEqual("pending", self.rig.key(), "the canonical spelling of the same key is held")

    def test_a_line_over_4096_bytes_is_refused_and_a_short_one_is_not_waited_for(self):
        self.assertEqual("refused", self.rig.ask(b"A" * 4097 + b"\n"))
        self.assertEqual("refused", self.rig.ask(b"A" * 5000))
        # the boundary: 4095 bytes of a line that has no end yet is still waiting; the 4096th byte without an end is too many
        s = self.rig.connect()
        s.sendall(b"A" * 4095)
        data, closed = self.rig.read(s, rounds=10)
        self.assertEqual((b"", False), (data, closed))
        s.sendall(b"A")
        data, closed = self.rig.read(s)
        self.assertEqual((b"paddock-pair/1 refused\n", True), (data, closed))
        # a whole request of exactly 4096 bytes, newline included, is read and judged on its content (refused here: it is not a request)
        self.assertEqual("refused", self.rig.ask(b"B" * 4095 + b"\n"))
        self.assertIsNone(self.l.held)

    def test_bytes_after_the_first_line_are_ignored(self):
        self.assertEqual("pending", self.rig.ask(("%s key %s %s\n" % (V, self.rig.sid, GOOD_LINE)).encode() + b"anything else\n" + b"B" * 300))
        self.assertEqual(GOOD_LINE, self.l.held.line)

    def test_a_request_may_arrive_in_pieces_and_a_client_may_half_close(self):
        s = self.rig.connect()
        line = ("%s status %s\n" % (V, self.rig.sid)).encode()
        s.sendall(line[:7])
        self.rig.pump()
        s.sendall(line[7:])
        s.shutdown(socket.SHUT_WR)
        data, closed = self.rig.read(s)
        self.assertEqual((b"paddock-pair/1 none\n", True), (data, closed))

    def test_a_second_different_key_is_busy_and_nothing_of_it_is_kept(self):
        self.assertEqual("pending", self.rig.key())
        self.assertEqual("busy", self.rig.key(OTHER_KEY_LINE))
        self.assertEqual(GOOD_LINE, self.l.held.line)
        self.assertEqual("pending", self.rig.status(), "the held key's state, not the sender's")
        self.l.finish(KEY)
        self.assertEqual("busy", self.rig.key(OTHER_KEY_LINE), "also after the first key was decided")
        self.assertEqual(GOOD_LINE, self.l.held.line)

    def test_the_same_key_again_answers_with_its_current_state(self):
        self.assertEqual("pending", self.rig.key())
        self.assertEqual("pending", self.rig.key())
        self.assertEqual("pending", self.rig.key(OTHER_LINE), "the same type and blob under another comment is the same key")
        self.assertEqual(GOOD_LINE, self.l.held.line, "the first line is the one held")
        self.l.finish(KEY)
        self.assertEqual("ok", self.rig.key())
        self.assertEqual("ok", self.rig.key(OTHER_LINE))

    def test_the_held_key_goes_pending_to_ok(self):
        self.rig.key()
        self.assertFalse(self.l.told)
        self.l.finish(KEY)
        self.assertEqual("ok", self.l.state)
        self.assertEqual("ok", self.rig.status())
        self.assertTrue(self.l.told)

    def test_the_held_key_goes_pending_to_rejected(self):
        self.rig.key()
        self.l.finish(None)
        self.assertEqual("rejected", self.rig.status())
        self.assertEqual("rejected", self.rig.key())

    def test_a_decision_for_another_key_rejects_the_held_one(self):
        # the first complete valid key wins; a phone whose key was not the one approved is told rejected
        self.rig.key()
        self.l.finish(pp.parse_key_line(OTHER_KEY_LINE))
        self.assertEqual("rejected", self.rig.status())

    def test_the_decision_is_made_once(self):
        self.rig.key()
        self.l.finish(KEY)
        self.l.finish(None)
        self.assertEqual("ok", self.rig.status())

    def test_a_pending_key_expires_with_the_window(self):
        self.rig.key()
        self.clock.advance(119.9)
        self.assertEqual("pending", self.rig.status())
        self.clock.advance(0.2)
        self.assertEqual("expired", self.rig.status())
        self.assertEqual("expired", self.rig.key(), "the same key, after the window")
        self.assertEqual("expired", self.rig.key(OTHER_KEY_LINE))
        self.assertTrue(self.l.told)

    def test_a_key_after_the_window_is_expired_and_not_stored(self):
        self.clock.advance(120.0)
        self.assertEqual("expired", self.rig.key())
        self.assertIsNone(self.l.held)
        self.assertEqual("none", self.rig.status())

    def test_a_wrong_sid_after_the_window_is_still_just_refused(self):
        self.clock.advance(500)
        self.assertEqual("refused", self.rig.key(sid=pp.new_sid()))

    def test_the_window_is_the_one_given(self):
        rig = Rig(window_s=30.0)
        self.addCleanup(rig.close)
        rig.key()
        rig.clock.advance(29)
        self.assertEqual("pending", rig.status())
        rig.clock.advance(1)
        self.assertEqual("expired", rig.status())

    def test_ok_and_rejected_stay_answerable_after_the_window_and_as_often_as_asked(self):
        self.rig.key()
        self.l.finish(KEY)
        for _ in range(3):
            self.assertEqual("ok", self.rig.status())
        self.clock.advance(1000)
        self.assertEqual("ok", self.rig.status())
        rig = Rig()
        self.addCleanup(rig.close)
        rig.key()
        rig.listener.finish(None)
        rig.clock.advance(1000)
        self.assertEqual("rejected", rig.status())
        self.assertEqual("rejected", rig.status())

    def test_a_key_that_came_by_another_intake_is_held_so_a_phone_cannot_replace_it(self):
        other = pp.parse_key_line(OTHER_KEY_LINE)
        self.assertTrue(self.l.adopt(other, "the camera"))
        self.assertFalse(self.l.adopt(KEY))
        self.assertEqual("pending", self.rig.status())
        self.assertEqual("busy", self.rig.key())
        self.assertEqual("pending", self.rig.key(OTHER_KEY_LINE), "the phone sending the same key is just told its state")
        self.l.finish(other)
        self.assertEqual("ok", self.rig.key(OTHER_KEY_LINE))

    def test_nothing_of_a_request_is_ever_echoed_or_logged(self):
        self.rig.key()
        self.rig.key(OTHER_KEY_LINE)
        self.rig.ask(("%s key %s %s %s\n" % (V, self.rig.sid, GOOD_LINE, MARK)).encode())
        self.rig.ask(("%s status %s%s\n" % (V, self.rig.sid, MARK)).encode())
        self.rig.ask(("%s %s\n" % (MARK, self.rig.sid)).encode())
        s = self.rig.connect()
        s.sendall(("%s key %s %s %s\n" % (V, pp.new_sid(), OTHER_KEY_LINE, MARK)).encode())
        data, _ = self.rig.read(s)
        self.assertEqual(b"paddock-pair/1 refused\n", data)
        everything = " ".join(self.l.log)
        for secret in (MARK, GOOD_BODY[:20], OTHER_BODY[:20], self.rig.sid, "ecdsa", "paddock@phone"):
            self.assertNotIn(secret, everything)
        for entry in self.l.log:
            word = entry.split(" -> ")[1]
            self.assertIn(word, pp.REPLY_WORDS)

    def test_every_reply_word_is_one_of_the_seven(self):
        seen = set()
        seen.add(self.rig.status())                        # none
        seen.add(self.rig.key())                           # pending
        seen.add(self.rig.key(OTHER_KEY_LINE))             # busy
        seen.add(self.rig.status(sid=pp.new_sid()))        # refused
        self.l.finish(KEY)
        seen.add(self.rig.status())                        # ok
        rig = Rig()
        self.addCleanup(rig.close)
        rig.key()
        rig.listener.finish(None)
        seen.add(rig.status())                             # rejected
        rig.clock.advance(1000)
        rig2 = Rig()
        self.addCleanup(rig2.close)
        rig2.key()
        rig2.clock.advance(1000)
        seen.add(rig2.status())                            # expired
        self.assertEqual(set(pp.REPLY_WORDS), seen)


class Limits(unittest.TestCase):
    def setUp(self):
        self.rig = Rig(rate_limit=pp.RATE_LIMIT)
        self.addCleanup(self.rig.close)
        self.l = self.rig.listener
        self.clock = self.rig.clock

    def test_the_defaults_are_the_documented_numbers(self):
        self.assertEqual((12, 60.0, 8, 5.0, 120.0, 4096), (pp.RATE_LIMIT, pp.RATE_WINDOW_S, pp.MAX_CONNECTIONS, pp.REQUEST_TIMEOUT_S, pp.PAIR_WINDOW_S, pp.MAX_REQUEST_BYTES))
        l = pp.PairListener("127.0.0.1", pp.new_sid())
        self.addCleanup(l.close)
        self.assertEqual((12, 60.0, 8, 5.0, 120.0), (l.rate_limit, l.rate_window_s, l.max_connections, l.request_timeout_s, l.window_s))

    def wrong(self, source=None):
        """A request that counts against the limit: a status with a wrong handle."""
        return self.rig.status(sid=pp.new_sid(), source=source)

    def test_the_thirteenth_counted_request_in_a_minute_from_one_address_is_busy(self):
        for n in range(12):
            self.assertEqual("refused", self.wrong(), n)
        self.assertEqual("busy", self.wrong())
        self.assertEqual("busy", self.wrong())
        self.assertIsNone(self.l.held)

    def test_a_status_poll_with_the_right_handle_is_free_every_two_seconds_for_two_minutes(self):
        self.assertEqual("pending", self.rig.key())
        words = []
        for _ in range(60):
            self.clock.advance(2.0)
            words.append(self.rig.status())
        self.assertEqual({"pending", "expired"}, set(words))
        self.assertNotIn("busy", words)
        self.assertEqual("pending", words[0])
        self.assertEqual("expired", words[-1])

    def test_a_polling_phone_hears_ok_or_rejected_without_ever_being_throttled(self):
        for decide, word in ((lambda l: l.finish(KEY), "ok"), (lambda l: l.finish(None), "rejected")):
            rig = Rig(rate_limit=pp.RATE_LIMIT)
            self.addCleanup(rig.close)
            rig.key()
            seen = []
            for n in range(60):
                rig.clock.advance(2.0)
                if n == 10:
                    decide(rig.listener)
                seen.append(rig.status())
            self.assertEqual({"pending", word}, set(seen))

    def test_a_status_with_the_right_handle_is_still_answered_from_a_throttled_address(self):
        for _ in range(12):
            self.wrong()
        self.assertEqual("busy", self.wrong())
        self.assertEqual("none", self.rig.status())
        self.assertEqual("busy", self.rig.key(), "a key is counted, so it is throttled")
        self.assertIsNone(self.l.held)

    def test_key_requests_count_even_when_they_are_valid_and_the_same_key(self):
        self.assertEqual("pending", self.rig.key())
        for n in range(11):
            self.assertEqual("pending", self.rig.key(), n)
        self.assertEqual("busy", self.rig.key())
        self.assertEqual("pending", self.rig.status(), "the phone can still ask for the held key's state")

    def test_a_request_over_the_limit_is_busy_whatever_it_says_and_nothing_is_looked_at(self):
        for _ in range(12):
            self.wrong()
        self.assertEqual("busy", self.rig.key())
        self.assertEqual("busy", self.rig.ask(b"garbage\n"))
        self.assertEqual("busy", self.rig.ask(b"A" * 5000))
        self.assertIsNone(self.l.held, "a key sent over the limit is not stored")

    def test_malformed_and_oversize_requests_count_too(self):
        for n in range(6):
            self.assertEqual("refused", self.rig.ask(b"garbage\n"), n)
        for n in range(6):
            self.assertEqual("refused", self.rig.ask(b"A" * 5000), n)
        self.assertEqual("busy", self.wrong())

    def test_the_limit_is_a_rolling_minute(self):
        for _ in range(6):
            self.wrong()
        self.clock.advance(30)
        for _ in range(6):
            self.wrong()
        self.assertEqual("busy", self.wrong())
        self.clock.advance(29.9)
        self.assertEqual("busy", self.wrong(), "the first six are 59.9 seconds old")
        self.clock.advance(0.2)
        self.assertEqual("refused", self.wrong(), "the first six are now over a minute old; six of the second batch remain")
        for _ in range(5):
            self.assertEqual("refused", self.wrong())
        self.assertEqual("busy", self.wrong())

    def test_the_limit_is_per_source_address(self):
        try:
            self.rig.connect("127.0.0.2").close()
        except OSError:
            self.skipTest("this host does not route all of 127/8 to loopback")
        for _ in range(12):
            self.wrong()
        self.assertEqual("busy", self.wrong())
        self.assertEqual("refused", self.wrong(source="127.0.0.2"))

    def test_the_limit_can_be_set(self):
        rig = Rig(rate_limit=2)
        self.addCleanup(rig.close)
        self.assertEqual(["refused", "refused", "busy"], [rig.status(sid=pp.new_sid()) for _ in range(3)])

    def test_at_most_eight_connections_at_once_and_the_ninth_is_closed_without_a_reply(self):
        held = [self.rig.connect() for _ in range(8)]
        ninth = self.rig.connect()
        self.rig.pump(5)
        data, closed = self.rig.read(ninth, rounds=20)
        self.assertEqual((b"", True), (data, closed))
        # the eight are still being served
        held[0].sendall(("%s status %s\n" % (V, self.rig.sid)).encode())
        data, closed = self.rig.read(held[0])
        self.assertEqual((b"paddock-pair/1 none\n", True), (data, closed))
        # one slot is free again once that client has gone
        held[0].close()
        self.rig.pump(5)
        tenth = self.rig.connect()
        tenth.sendall(("%s status %s\n" % (V, self.rig.sid)).encode())
        data, _ = self.rig.read(tenth)
        self.assertEqual(b"paddock-pair/1 none\n", data)

    def test_a_connection_that_sends_nothing_is_dropped_after_five_seconds_without_a_reply(self):
        s = self.rig.connect()
        self.rig.pump()
        self.clock.advance(4.9)
        data, closed = self.rig.read(s, rounds=5)
        self.assertEqual((b"", False), (data, closed))
        self.clock.advance(0.2)
        data, closed = self.rig.read(s, rounds=20)
        self.assertEqual((b"", True), (data, closed))

    def test_a_slow_client_that_never_finishes_its_line_is_dropped_without_a_reply(self):
        s = self.rig.connect()
        s.sendall(("%s status %s" % (V, self.rig.sid)).encode())  # no newline
        self.rig.pump()
        self.clock.advance(5.0)
        data, closed = self.rig.read(s, rounds=20)
        self.assertEqual((b"", True), (data, closed))
        self.assertIsNone(self.l.held)

    def test_a_slow_client_cannot_use_up_the_connections_for_long(self):
        for _ in range(8):
            self.rig.connect()
        self.rig.pump(5)
        self.clock.advance(5.0)
        self.rig.pump(5)
        self.assertEqual("none", self.rig.status(), "the eight idle connections were dropped, so a real request gets through")

    def test_a_client_that_keeps_sending_after_its_reply_is_cut_off_at_the_deadline(self):
        s = self.rig.connect()
        s.sendall(("%s status %s\n" % (V, self.rig.sid)).encode() + b"x" * 100)
        data, closed = self.rig.read(s, rounds=10)
        self.assertEqual(b"paddock-pair/1 none\n", data)
        self.clock.advance(5.0)
        _, closed = self.rig.read(s, rounds=20)
        self.assertTrue(closed)


class Lifecycle(unittest.TestCase):
    def test_close_frees_the_port_and_is_safe_twice(self):
        rig = Rig()
        port = rig.listener.port
        self.assertTrue(1 <= port <= 65535)
        rig.close()
        rig.listener.close()
        with self.assertRaises(OSError):
            socket.create_connection(("127.0.0.1", port), timeout=1).close()

    def test_close_ends_open_connections(self):
        rig = Rig()
        s = rig.connect()
        rig.pump()
        rig.listener.close()
        try:
            data = s.recv(10)
        except BlockingIOError:
            self.fail("the connection was left open")
        except OSError:
            data = b""
        self.assertEqual(b"", data)
        rig.close()

    def test_it_runs_on_a_selector_the_caller_owns(self):
        sel = selectors.DefaultSelector()
        listener = pp.PairListener("127.0.0.1", pp.new_sid(), selector=sel)
        try:
            self.assertEqual(1, len(sel.get_map()), "only the listening socket so far")
            c = socket.create_connection(("127.0.0.1", listener.port), timeout=2)
            c.sendall(("%s status %s\n" % (V, listener._sid.decode())).encode())
            data = b""
            for _ in range(50):
                for key, mask in sel.select(0.05):
                    key.data(key.fileobj, mask)
                c.settimeout(0.01)
                try:
                    chunk = c.recv(100)
                except socket.timeout:
                    continue
                if not chunk:
                    break
                data += chunk
            self.assertEqual(b"paddock-pair/1 none\n", data)
            c.close()
        finally:
            listener.close()
            self.assertEqual(0, len(sel.get_map()), "close() removes every socket it registered")
            sel.close()

    def test_an_address_the_listener_may_not_bind_is_refused(self):
        for ip in ("0.0.0.0", "255.255.255.255", "224.0.0.1", "8.8.8.8", "::1", "localhost", "", "999.1.1.1", "127.0.0.1 "):
            with self.subTest(ip):
                with self.assertRaises(pp.Refusal):
                    pp.PairListener(ip, pp.new_sid())

    def test_lan_addresses_are_allowed(self):
        for ip in ("127.0.0.1", "10.1.2.3", "172.16.0.9", "192.168.1.20", "169.254.3.4", "100.64.1.2"):
            with self.subTest(ip):
                self.assertIsNone(pp.listen_address_problem(ip))
        for ip in ("1.1.1.1", "93.184.216.34", "0.0.0.0", "224.0.0.251"):
            with self.subTest(ip):
                self.assertIsNotNone(pp.listen_address_problem(ip))

    def test_a_bad_sid_is_refused(self):
        for sid in ("", "short", "A" * 23, "A" * 21 + "!", None, 5, "A" * 21 + "\n"):
            with self.subTest(sid=sid):
                with self.assertRaises(pp.Refusal):
                    pp.PairListener("127.0.0.1", sid)

    def test_a_port_in_use_is_a_refusal_not_a_traceback(self):
        rig = Rig()
        self.addCleanup(rig.close)
        with self.assertRaises(pp.Refusal) as ctx:
            pp.PairListener("127.0.0.1", pp.new_sid(), port=rig.listener.port)
        self.assertIn("Could not listen", ctx.exception.message)

    def test_each_listener_gets_a_random_port(self):
        rigs = [Rig() for _ in range(4)]
        try:
            self.assertEqual(4, len({r.listener.port for r in rigs}))
        finally:
            for r in rigs:
                r.close()


if __name__ == "__main__":
    unittest.main()
