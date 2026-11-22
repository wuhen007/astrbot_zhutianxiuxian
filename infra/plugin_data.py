"""Plugin-owned data directory setup and one-time legacy migration."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path


def _merge_missing(source: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    for entry in source.iterdir():
        destination = target / entry.name
        if destination.exists():
            if entry.is_dir() and destination.is_dir():
                _merge_missing(entry, destination)
            continue
        shutil.move(str(entry), str(destination))


def prepare_plugin_data_dir(plugin_dir: Path, legacy_dir: Path) -> Path:
    """Copy the old fixed-name data directory without replacing plugin data."""
    plugin_dir = Path(plugin_dir)
    legacy_dir = Path(legacy_dir)
    plugin_dir.parent.mkdir(parents=True, exist_ok=True)
    plugin_dir.mkdir(parents=True, exist_ok=True)

    if not (legacy_dir / "zhutian.db").is_file() or (plugin_dir / "zhutian.db").exists():
        return plugin_dir

    staging = Path(tempfile.mkdtemp(prefix=f".{plugin_dir.name}-migration-",
                                    dir=plugin_dir.parent))
    try:
        shutil.copytree(legacy_dir, staging, dirs_exist_ok=True)
        if not any(plugin_dir.iterdir()):
            plugin_dir.rmdir()
            try:
                staging.replace(plugin_dir)
            except FileExistsError:
                _merge_missing(staging, plugin_dir)
        else:
            _merge_missing(staging, plugin_dir)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return plugin_dir
