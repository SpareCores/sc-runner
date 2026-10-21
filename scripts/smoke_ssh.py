"""SSH public key helper for local smoke scripts (no embedded keys)."""

from __future__ import annotations

import os
import sys


def require_ssh_public_key() -> str:
    """Return SSH_PUBLIC_KEY from the environment, or exit with a clear error."""
    key = os.environ.get("SSH_PUBLIC_KEY", "").strip()
    if not key:
        print(
            "SSH_PUBLIC_KEY must be set to your SSH public key "
            "(no default key is embedded in this repository).",
            file=sys.stderr,
        )
        raise SystemExit(2)
    return key
