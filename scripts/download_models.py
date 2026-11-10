"""Pinned, checksum-verified downloads. All large artifacts stay in the project."""
from __future__ import annotations

import concurrent.futures
import hashlib
import json
import tarfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASR_NAME = "sherpa-onnx-qwen3-asr-0.6B-int8-2026-03-25"
HF_REV = "a06e946bb6b655725eafa393f4a9745d460374c9"
ARTIFACTS = [
    ("asr.tar.bz2", f"https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/{ASR_NAME}.tar.bz2",
     "393f8a14e2f5fb96746aaab342997a40641001fbd5bf9592a080a8329178ee96"),
    ("silero_vad.onnx", "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/silero_vad.onnx",
     "9e2449e1087496d8d4caba907f23e0bd3f78d91fa552479bb9c23ac09cbb1fd6"),
    ("Qwen3-4B-Instruct-2507-Q4_K_M.gguf",
     f"https://huggingface.co/unsloth/Qwen3-4B-Instruct-2507-GGUF/resolve/{HF_REV}/Qwen3-4B-Instruct-2507-Q4_K_M.gguf",
     "3605803b982cb64aead44f6c1b2ae36e3acdb41d8e46c8a94c6533bc4c67e597"),
    ("llama-cuda.zip", "https://github.com/ggml-org/llama.cpp/releases/download/b12244/llama-b12244-bin-win-cuda-12.4-x64.zip",
     "16eef900b8e952a11c6c654ce9a48e7be124067bdc480acca01cfd581aa122ab"),
    ("llama-cudart.zip", "https://github.com/ggml-org/llama.cpp/releases/download/b12244/cudart-llama-bin-win-cuda-12.4-x64.zip",
     "8c79a9b226de4b3cacfd1f83d24f962d0773be79f1e7b75c6af4ded7e32ae1d6"),
]


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def download(item: tuple[str, str, str]) -> Path:
    name, url, expected = item
    target = ROOT / "models" / name
    target.parent.mkdir(exist_ok=True)
    if target.exists() and sha256(target) == expected:
        print(f"Verified cached {name}", flush=True)
        return target
    partial = target.with_suffix(target.suffix + ".part")
    for attempt in range(5):
        offset = partial.stat().st_size if partial.exists() else 0
        headers = {"User-Agent": "YouTubeLocalSubtitles/0.1", "Range": f"bytes={offset}-"} if offset else {"User-Agent": "YouTubeLocalSubtitles/0.1"}
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=90) as response:
                append = offset > 0 and response.status == 206
                if not append:
                    offset = 0
                total = offset + int(response.headers.get("Content-Length", 0))
                last = time.monotonic()
                with partial.open("ab" if append else "wb") as output:
                    while chunk := response.read(2 * 1024 * 1024):
                        output.write(chunk)
                        offset += len(chunk)
                        if time.monotonic() - last > 20:
                            print(f"{name}: {offset / 1024**2:.0f}/{total / 1024**2:.0f} MiB", flush=True)
                            last = time.monotonic()
            if sha256(partial) != expected:
                # Retain the mismatched file for diagnosis, never execute/extract it.
                partial.rename(partial.with_suffix(f".bad-{int(time.time())}"))
                raise ValueError(f"Checksum mismatch: {name}")
            partial.replace(target)
            print(f"Downloaded and verified {name}", flush=True)
            return target
        except (OSError, urllib.error.URLError) as error:
            print(f"Retry {attempt + 1}: {name}: {type(error).__name__}", flush=True)
            time.sleep(min(2 ** attempt, 8))
    raise RuntimeError(f"Download failed: {name}")


def main() -> None:
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(download, ARTIFACTS))
    models = ROOT / "models"
    if not (models / ASR_NAME / "decoder.int8.onnx").exists():
        with tarfile.open(models / "asr.tar.bz2") as archive:
            archive.extractall(models, filter="data")
    runtime = ROOT / "runtime" / "llama"
    runtime.mkdir(parents=True, exist_ok=True)
    for name in ("llama-cuda.zip", "llama-cudart.zip"):
        with zipfile.ZipFile(models / name) as archive:
            for entry in archive.infolist():
                resolved = (runtime / entry.filename).resolve()
                if not resolved.is_relative_to(runtime.resolve()):
                    raise ValueError("Invalid archive path")
            archive.extractall(runtime)
    (models / "manifest.json").write_text(json.dumps([
        {"file": name, "url": url, "sha256": digest} for name, url, digest in ARTIFACTS
    ], indent=2), encoding="utf-8")
    print("All artifacts ready. Upstream licenses remain with the downloaded models.", flush=True)


if __name__ == "__main__":
    main()
