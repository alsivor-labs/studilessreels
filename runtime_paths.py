"""Paths that work both from the source checkout and the Windows release build."""
import os
import sys
from pathlib import Path


def resource_root():
    """Read-only application files (web UI and ComfyUI workflows)."""
    if getattr(sys, 'frozen', False):
        return Path(getattr(sys, '_MEIPASS', Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parent


def data_home():
    """Writable user data, outside the one-file executable's temporary folder."""
    configured = os.environ.get('HISTORIAS_HOME')
    if configured:
        return Path(configured).expanduser().resolve()
    if getattr(sys, 'frozen', False):
        base = os.environ.get('LOCALAPPDATA') or str(Path.home() / 'AppData' / 'Local')
        return Path(base) / 'Historias Studio'
    return resource_root()