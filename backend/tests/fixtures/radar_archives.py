"""Bundled radar archive paths for integration tests (no network / /opt/cursor deps)."""

from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path

_FIXTURES = Path(__file__).resolve().parent / "radar_archives"
AUG25_FUNNEL = _FIXTURES / "aug25" / "funnel_events.jsonl"
AUG27_ALL_RADARS = _FIXTURES / "aug27" / "all_radars.json"
AUG27_ZIP = _FIXTURES / "aug27" / "radar-2026-08-27.zip"


def aug25_funnel_path() -> Path:
    """Return bundled Aug25 funnel_events.jsonl (extracted from prod archive)."""
    if not AUG25_FUNNEL.is_file():
        raise FileNotFoundError(f"Missing bundled fixture: {AUG25_FUNNEL}")
    return AUG25_FUNNEL


def ensure_aug27_archive(dest: Path | str = "/tmp/radar/radar-2026-08-27.zip") -> Path:
    """Materialize Aug27 radar ZIP for tests that read all_radars.json."""
    target = Path(dest)
    if target.is_file() and target.stat().st_size >= 1000:
        return target

    if not AUG27_ALL_RADARS.is_file():
        raise FileNotFoundError(f"Missing bundled fixture: {AUG27_ALL_RADARS}")

    target.parent.mkdir(parents=True, exist_ok=True)
    if AUG27_ZIP.is_file() and AUG27_ZIP.stat().st_size >= 1000:
        shutil.copy2(AUG27_ZIP, target)
        return target

    payload = AUG27_ALL_RADARS.read_text(encoding="utf-8")
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("all_radars.json", payload)
        zf.writestr(
            "manifest.json",
            json.dumps({"date": "2026-08-27", "source": "test_fixture"}),
        )
    return target
