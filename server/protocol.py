from __future__ import annotations

import math
import struct
from dataclasses import dataclass

import numpy as np

HEADER = struct.Struct("<4sIIdfI4x")
SAMPLE_RATE = 16000
MODES = {"english", "chinese", "bilingual"}


@dataclass(frozen=True)
class AudioFrame:
    generation: int
    sequence: int
    media_start: float
    rate: float
    samples: np.ndarray


def decode_audio(data: bytes) -> AudioFrame:
    if len(data) < HEADER.size:
        raise ValueError("Audio header missing")
    magic, generation, sequence, media, rate, count = HEADER.unpack_from(data)
    if magic != b"YTLS" or not 0 < generation < 2**31:
        raise ValueError("Invalid audio header")
    if not math.isfinite(media) or media < 0 or not math.isfinite(rate) or not 0.25 <= rate <= 4:
        raise ValueError("Invalid audio timing")
    if not 1 <= count <= 3200 or len(data) != HEADER.size + count * 2:
        raise ValueError("Invalid audio length")
    samples = np.frombuffer(data, dtype="<i2", offset=HEADER.size).astype(np.float32) / 32768
    return AudioFrame(generation, sequence, media, rate, samples)
