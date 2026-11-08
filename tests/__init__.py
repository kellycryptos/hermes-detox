"""Detox test suite."""

import os
from pathlib import Path
import sys

# Ensure agent.redact from hermes-agent is importable for tests
try:
    import agent.redact
except ImportError:
    for candidate in (
        os.environ.get("HERMES_AGENT_PATH"),
        str(Path.home() / "AppData" / "Local" / "hermes" / "hermes-agent"),
        r"C:\Users\HP\AppData\Local\hermes\hermes-agent",
        "/tmp/hermes-agent",
        str(Path(__file__).resolve().parent.parent.parent / "hermes-repo"),
        str(Path(__file__).resolve().parent.parent.parent / "hermes_pkg"),
    ):
        if candidate and os.path.isdir(candidate) and candidate not in sys.path:
            sys.path.insert(0, candidate)
            try:
                import agent.redact
                break
            except ImportError:
                pass
