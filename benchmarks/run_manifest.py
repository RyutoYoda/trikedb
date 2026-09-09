"""Configuration fingerprints for resumable benchmark logs (no credentials)."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


def check_resume(out: Path, config: dict, inputs: list[Path]) -> None:
    """Refuse to mix runs; legacy logs remain scoreable but cannot be appended."""
    expected = dict(config, inputs_sha256=[
        hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs])
    manifest = out.with_suffix(out.suffix + '.manifest.json')
    if out.exists() and out.stat().st_size:
        if not manifest.exists() or json.loads(manifest.read_text()) != expected:
            raise ValueError('Resume configuration differs or is unrecorded; use a new output path')
    out.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps(expected, indent=2) + '\n')
