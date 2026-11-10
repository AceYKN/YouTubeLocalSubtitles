from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_VERSION = "0.2.0"
ASR_NAME = "sherpa-onnx-qwen3-asr-0.6B-int8-2026-03-25"
PORT = 18765
TRANSLATION_PORT = 18766


def extension_id() -> str:
    manifest = json.loads((ROOT / "extension/manifest.json").read_text(encoding="utf-8"))
    digest = hashlib.sha256(base64.b64decode(manifest["key"])).hexdigest()[:32]
    return "".join(chr(ord("a") + int(char, 16)) for char in digest)


def load_config() -> dict:
    path = ROOT / "config.local.json"
    if path.exists():
        config = json.loads(path.read_text(encoding="utf-8"))
    else:
        config = {"token": secrets.token_urlsafe(32), "port": PORT,
                  "translation_port": TRANSLATION_PORT, "threads": 6}
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(config, indent=2), encoding="utf-8")
        os.replace(temporary, path)
    config["extension_id"] = extension_id()
    return config
