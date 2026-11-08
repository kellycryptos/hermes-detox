"""Detox test suite."""

import importlib.util
import os
from pathlib import Path
import sys

# Ensure agent.redact and hermes_cli from hermes-agent are importable for tests
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

try:
    from hermes_cli.plugins import PluginManager
except ImportError:
    import glob
    for p in glob.glob(str(Path.home() / "AppData" / "Local" / "hermes" / "installs" / "*" / "environments" / "*" / "venv" / "Lib" / "site-packages")):
        if os.path.isdir(p) and p not in sys.path:
            sys.path.insert(0, p)
            try:
                from hermes_cli.plugins import PluginManager
                break
            except ImportError:
                pass

# Load plugin as package identical to Hermes loader
_PKG_DIR = Path(__file__).resolve().parent.parent
if "hermes_detox" not in sys.modules:
    _spec = importlib.util.spec_from_file_location(
        "hermes_detox",
        str(_PKG_DIR / "__init__.py"),
        submodule_search_locations=[str(_PKG_DIR)],
    )
    _mod = importlib.util.module_from_spec(_spec)
    _mod.__package__ = "hermes_detox"
    _mod.__path__ = [str(_PKG_DIR)]
    sys.modules["hermes_detox"] = _mod
    _spec.loader.exec_module(_mod)
