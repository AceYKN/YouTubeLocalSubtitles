"""Read only the requested public YouTube audio, ahead of the playback cursor."""
from __future__ import annotations

import threading
import os
from pathlib import Path
from urllib.parse import urlparse

import av
import numpy as np
from yt_dlp import YoutubeDL

from .config import ROOT

_plugin_lock = threading.Lock()
_plugins_loaded = False


class QuietLogger:
    def debug(self, *_): pass
    def warning(self, *_): pass
    def error(self, *_): pass


class AudioReader:
    def __init__(self, video_id: str, local_file: Path | None = None):
        self.video_id = video_id
        self.local_file = local_file
        self.container = None
        self.audio = None
        self.decoder = None
        self.resampler = None
        self.pending = None
        self.cursor = None
        self.duration = 0.0
        self.lock = threading.RLock()

    def open(self):
        with self.lock:
            if self.container is not None:
                return
            options = {}
            if self.local_file is not None:
                source = str(self.local_file)
            else:
                global _plugins_loaded
                provider = ROOT / "runtime/bgutil/server"
                if not (provider / "build/generate_once.js").exists():
                    raise FileNotFoundError("MEDIA_PROVIDER_MISSING")
                os.environ["XDG_CACHE_HOME"] = str(ROOT / "cache")
                with _plugin_lock:
                    if not _plugins_loaded:
                        from yt_dlp.plugins import load_all_plugins
                        load_all_plugins()
                        _plugins_loaded = True
                with YoutubeDL({"quiet": True, "no_warnings": True, "logger": QuietLogger(),
                                "format": "bestaudio", "noplaylist": True, "socket_timeout": 10,
                                "retries": 1, "extractor_retries": 1, "js_runtimes": {"node": {}},
                                "cachedir": str(ROOT / "cache/yt-dlp"),
                                "extractor_args": {
                                    "youtube": {"player_client": ["mweb"]},
                                    "youtubepot-bgutilscript": {"server_home": [str(provider)]},
                                }}) as ydl:
                    info = ydl.extract_info(f"https://www.youtube.com/watch?v={self.video_id}", download=False)
                source = info.get("url", "")
                parsed = urlparse(source)
                if parsed.scheme != "https" or not parsed.hostname or not parsed.hostname.endswith(".googlevideo.com"):
                    raise ValueError("Unsupported media source")
                self.duration = float(info.get("duration") or 0)
                headers = info.get("http_headers", {})
                options["headers"] = "".join(f"{key}: {value}\r\n" for key, value in headers.items())
                options["protocol_whitelist"] = "https,http,tcp,tls,crypto"
            self.container = av.open(source, options=options, timeout=(12, 8))
            self.audio = self.container.streams.audio[0]
            self.audio.thread_count = 1
            if not self.duration and self.container.duration:
                self.duration = float(self.container.duration / av.time_base)

    def read(self, start: float, duration: float = 4.0) -> tuple[float, np.ndarray]:
        with self.lock:
            self.open()
            start = max(0.0, start)
            end = min(start + duration, self.duration) if self.duration else start + duration
            if self.cursor is None or abs(self.cursor - start) > 0.025:
                self.container.seek(int(start / self.audio.time_base), stream=self.audio, backward=True)
                self.decoder = iter(self.container.decode(self.audio))
                self.resampler = av.AudioResampler(format="fltp", layout="mono", rate=16000)
                self.pending = None
            chunks = []
            first = None
            while True:
                if self.pending is not None:
                    timestamp, samples = self.pending
                    self.pending = None
                else:
                    try:
                        frame = next(self.decoder)
                    except StopIteration:
                        break
                    if frame.time is None:
                        raise ValueError("Media timestamps unavailable")
                    outputs = self.resampler.resample(frame)
                    if not outputs:
                        continue
                    # Resampling retains a presentation timestamp in the new time base.
                    output = outputs[0]
                    timestamp = float(output.time) if output.time is not None else float(frame.time)
                    samples = output.to_ndarray().reshape(-1).astype(np.float32, copy=False)
                left = max(0, int(round((start - timestamp) * 16000)))
                right = min(len(samples), max(0, int(round((end - timestamp) * 16000))))
                if right > left:
                    if first is None:
                        first = timestamp + left / 16000
                    chunks.append(samples[left:right].copy())
                if timestamp + len(samples) / 16000 >= end:
                    if right < len(samples):
                        self.pending = (timestamp + right / 16000, samples[right:].copy())
                    break
            self.cursor = end
            return (first if first is not None else start), np.concatenate(chunks) if chunks else np.empty(0, dtype=np.float32)

    def close(self):
        with self.lock:
            if self.container:
                self.container.close()
            self.container = None
            self.decoder = None
            self.pending = None
