"""Shared fixtures: a real phone-shaped key line (made by ssh-keygen, its fingerprint as ssh-keygen -lf printed it) and paths."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
BIN = os.path.join(ROOT, "bin")

GOOD_BODY = "AAAAE2VjZHNhLXNoYTItbmlzdHAyNTYAAAAIbmlzdHAyNTYAAABBBDs4KFzkvvqVFPYDxa2EizNBQd5UQ9AM/rf/BkbRy451zNM6awvNfbey63bdDXFdhPna0H8xa4ZtvdeRXhUXwFw="
GOOD_LINE = "ecdsa-sha2-nistp256 " + GOOD_BODY + " paddock@phone"
GOOD_FINGERPRINT = "SHA256:StLaLXC/IrdkIci2a2J8q0glZkLFcuMPXtoVtP6XLmk"
OTHER_LINE = "ecdsa-sha2-nistp256 " + GOOD_BODY + " other-comment"
