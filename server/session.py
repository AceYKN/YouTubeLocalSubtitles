from __future__ import annotations

import asyncio
import contextlib
import math
import re
import time
from collections import deque

from .protocol import MODES, decode_audio


class Session:
    def __init__(self, engine, websocket):
        self.engine = engine
        self.websocket = websocket
        self.send_lock = asyncio.Lock()
        self.asr_queue = asyncio.Queue(maxsize=2)
        self.mt_queue = asyncio.Queue(maxsize=2)
        self.generation = 0
        self.mode = "bilingual"
        self.session_id = ""
        self.video_id = ""
        self.sequence = -1
        self.active = False
        self.accepting = False
        self.vad = None
        self.base_media = None
        self.rate = 1.0
        self.segment_id = 0
        self.history = deque(maxlen=2)
        self.mode_revision = 0
        self.last_caption = None
        self.source = "live"
        self.media_position = 0.0
        self.position_at = time.monotonic()
        self.playing = False
        self.position_rate = 1.0
        self.prefetch_cache = {}
        self.replay_cache = False
        self.tasks = []
        self.metrics = {"frames": 0, "segments": 0, "asr_completed": 0, "peak": 0.0, "resets": 0, "generation": 0, "reset_reason": ""}

    async def send(self, message):
        async with self.send_lock:
            await self.websocket.send_json(message)

    async def status(self, code, detail=""):
        await self.send({"type": "status", "code": code, "detail": detail,
                         "generation": self.generation})

    def clear(self):
        for queue in (self.asr_queue, self.mt_queue):
            while not queue.empty():
                queue.get_nowait()
        self.base_media = None
        self.sequence = -1
        self.history.clear()
        self.vad = None
        self.last_caption = None

    async def control(self, message):
        kind = message.get("type")
        if kind == "session.start":
            if self.engine.active not in (None, self):
                await self.status("SESSION_BUSY")
                return
            if message.get("mode") not in MODES:
                raise ValueError("Invalid mode")
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", message.get("video_id", "")):
                raise ValueError("Invalid video")
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", message.get("session_id", "")):
                raise ValueError("Invalid session")
            self.engine.active = self
            self.source = message.get("source", "live")
            if self.source not in ("live", "prefetch"):
                raise ValueError("Invalid source")
            if self.source == "prefetch" and not re.fullmatch(r"[A-Za-z0-9_-]{11}", message["video_id"]):
                raise ValueError("Invalid YouTube video")
            self.mode = message["mode"]
            self.session_id = message["session_id"]
            await self.reset(message)
            if not self.tasks:
                self.tasks = [asyncio.create_task(self.prefetch_worker())] if self.source == "prefetch" else [asyncio.create_task(self.asr_worker()), asyncio.create_task(self.mt_worker())]
            await self.status("READY")
        elif kind == "session.reset":
            if self.engine.active is self:
                await self.reset(message)
        elif kind == "session.mode":
            if message.get("mode") not in MODES:
                raise ValueError("Invalid mode")
            previous_mode = self.mode
            self.mode = message["mode"]
            self.replay_cache = True
            if previous_mode == "english" or self.mode == "english":
                self.mode_revision += 1
            if self.mode == "english":
                while not self.mt_queue.empty():
                    self.mt_queue.get_nowait()
            elif previous_mode == "english" and self.last_caption is not None:
                if time.monotonic() - self.last_caption["queued_at"] <= 8:
                    await self.enqueue(self.mt_queue, {**self.last_caption, "mode_revision": self.mode_revision})
            await self.status("MODE_CHANGED")
        elif kind == "session.pause":
            if self.engine.active is self:
                if self.source == "prefetch":
                    self.playing = False
                    return
                self.accepting = False
                if self.vad is not None and self.base_media is not None:
                    self.vad.flush()
                    await self.drain_vad()
                self.vad = None
                self.base_media = None
        elif kind == "session.resume":
            if self.engine.active is self and message.get("generation") == self.generation:
                if self.source == "prefetch":
                    self.playing = True
                    return
                self.active = True
                self.accepting = True
                self.base_media = None
                self.vad = self.engine.make_vad()
        elif kind == "session.position":
            if self.source == "prefetch" and message.get("generation") == self.generation:
                self.update_position(message)
        elif kind == "session.stop":
            self.active = False
            self.accepting = False
            self.clear()
            self.prefetch_cache.clear()
            if self.engine.active is self:
                self.engine.active = None
        else:
            raise ValueError("Unknown message")

    async def reset(self, message):
        generation = message.get("generation")
        if type(generation) is not int or not self.generation < generation < 2**31:
            raise ValueError("Invalid generation")
        video = message.get("video_id", self.video_id)
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", video):
            raise ValueError("Invalid video")
        self.generation = generation
        self.metrics["resets"] += 1
        self.metrics["generation"] = generation
        self.metrics["reset_reason"] = str(message.get("reason", "start"))[:32]
        if self.video_id != video:
            self.prefetch_cache.clear()
        self.video_id = video
        self.active = (message.get("eligible", message.get("active")) is True) if self.source == "prefetch" else message.get("active") is True
        self.accepting = self.active and self.source == "live"
        self.update_position(message)
        self.replay_cache = True
        self.clear()
        if self.accepting:
            self.vad = self.engine.make_vad()

    def update_position(self, message):
        position = message.get("media_time", self.media_position)
        rate = message.get("rate", self.position_rate)
        if not isinstance(position, (int, float)) or not math.isfinite(position) or position < 0:
            raise ValueError("Invalid position")
        if not isinstance(rate, (int, float)) or not math.isfinite(rate) or not 0.25 <= rate <= 4:
            raise ValueError("Invalid rate")
        self.media_position = float(position)
        self.position_rate = float(rate)
        self.playing = message.get("playing", message.get("active", self.playing)) is True
        self.position_at = time.monotonic()

    def position(self):
        elapsed = min(2.0, time.monotonic() - self.position_at) if self.playing else 0
        return self.media_position + elapsed * self.position_rate

    async def emit_cached(self, entry):
        if not self.active:
            return
        event = {key: entry[key] for key in ("segment_id", "media_start", "media_end")}
        event.update(session_id=self.session_id, generation=self.generation, source="prefetch")
        await self.send({**event, "type": "caption.source", "text": entry["text"], "language": "en"})
        if entry.get("zh") and self.mode != "english":
            await self.send({**event, "type": "caption.translation", "text": entry["zh"], "language": "zh"})

    async def prefetch_worker(self):
        from .media import AudioReader
        reader = None
        reader_video = ""
        cursor = None
        history = deque(maxlen=2)
        worker_generation = 0
        try:
            while True:
                if not self.active:
                    await asyncio.sleep(0.2)
                    continue
                if reader_video != self.video_id:
                    if reader:
                        await asyncio.to_thread(reader.close)
                    reader_video = self.video_id
                    factory = self.engine.media_factory or AudioReader
                    reader = factory(reader_video)
                    cursor = None
                    history.clear()
                    await self.status("PREPARING_SYNC")
                    preparations = [asyncio.to_thread(reader.open), self.engine.prepare()]
                    if self.mode != "english":
                        preparations.append(self.engine.translator.ensure_ready())
                    await asyncio.gather(*preparations)
                position = self.position()
                if worker_generation != self.generation:
                    worker_generation = self.generation
                    cursor = None
                if self.replay_cache:
                    self.replay_cache = False
                    for entry in list(self.prefetch_cache.values()):
                        if position - 30 < entry["media_end"] and entry["media_start"] < position + 24:
                            if self.mode != "english" and not entry.get("zh") and entry["media_end"] > position and entry["media_start"] < position + 8:
                                entry["zh"] = await self.engine.translator.translate(entry["text"], list(history))
                            await self.emit_cached(entry)
                if cursor is None or cursor < position + 0.4 or cursor > position + 28:
                    cursor = math.ceil((position + 4) / 4) * 4
                if (reader.duration and cursor >= reader.duration) or cursor >= position + 20:
                    await asyncio.sleep(0.25)
                    continue
                entry = self.prefetch_cache.get(cursor)
                if entry is not None:
                    if self.mode != "english" and not entry.get("zh"):
                        entry["zh"] = await self.engine.translator.translate(entry["text"], list(history))
                    await self.emit_cached(entry)
                    cursor += 4
                    continue
                timestamp, samples = await asyncio.to_thread(reader.read, cursor, 4.0)
                if self.video_id != reader_video or not self.active:
                    continue
                if len(samples) < 800:
                    cursor += 4
                    continue
                result = await self.engine.recognize(samples)
                if self.video_id != reader_video or not self.active:
                    continue
                self.metrics["asr_completed"] += 1
                self.metrics["last_asr_seconds"] = result["inference_seconds"]
                text = result["text"]
                if not text:
                    cursor += 4
                    continue
                self.segment_id += 1
                entry = {"segment_id": self.segment_id, "media_start": timestamp,
                         "media_end": timestamp + len(samples) / 16000, "text": text, "zh": ""}
                self.prefetch_cache[cursor] = entry
                if len(self.prefetch_cache) > 64:
                    del self.prefetch_cache[next(iter(self.prefetch_cache))]
                self.metrics["prefetch_cues"] = len(self.prefetch_cache)
                self.metrics["lead_seconds"] = round(entry["media_start"] - self.position(), 2)
                await self.emit_cached(entry)
                if self.mode != "english":
                    entry["zh"] = await self.engine.translator.translate(text, list(history))
                    if self.video_id == reader_video and self.active:
                        await self.emit_cached(entry)
                history.append(text)
                self.engine.last_error = None
                await self.status("SYNC_READY")
                cursor += 4
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self.engine.last_error = {"component": "media_prefetch", "type": type(error).__name__}
            # Never hide this failure by silently starting heavy screen capture.
            await self.status("MEDIA_PREFETCH_FAILED")
        finally:
            if reader:
                await asyncio.to_thread(reader.close)

    async def enqueue(self, queue, item):
        if queue.full():
            queue.get_nowait()
            await self.status("QUEUE_OVERFLOW")
        queue.put_nowait(item)

    async def audio(self, data):
        frame = decode_audio(data)
        if not self.accepting or self.engine.active is not self or frame.generation != self.generation:
            return
        if frame.sequence <= self.sequence:
            raise ValueError("Out-of-order audio")
        if self.base_media is None:
            self.base_media = frame.media_start
            self.rate = frame.rate
        if abs(self.rate - frame.rate) > 0.001:
            raise ValueError("Playback rate changed without reset")
        self.sequence = frame.sequence
        self.metrics["frames"] += 1
        self.metrics["peak"] = max(self.metrics["peak"], float(abs(frame.samples).max()))
        self.vad.accept_waveform(frame.samples)
        await self.drain_vad()

    async def drain_vad(self):
        while not self.vad.empty():
            segment = self.vad.front
            self.segment_id += 1
            self.metrics["segments"] += 1
            payload = {"samples": segment.samples.copy(), "generation": self.generation,
                       "segment_id": self.segment_id,
                       "media_start": self.base_media + segment.start / 16000 * self.rate,
                       "media_end": self.base_media + (segment.start + len(segment.samples)) / 16000 * self.rate,
                       "queued_at": time.monotonic()}
            self.vad.pop()
            await self.enqueue(self.asr_queue, payload)

    def valid(self, item):
        return self.active and self.engine.active is self and item["generation"] == self.generation

    async def asr_worker(self):
        while True:
            item = await self.asr_queue.get()
            if not self.valid(item):
                continue
            try:
                await self.status("RECOGNIZING")
                result = await self.engine.recognize(item["samples"])
                self.metrics["asr_completed"] += 1
                if not self.valid(item) or not result["text"]:
                    continue
                language = result.get("language", "").lower()
                text = result["text"]
                cjk = sum("\u4e00" <= c <= "\u9fff" for c in text)
                if language not in ("", "en", "english") or cjk > max(2, len(text) * 0.2):
                    await self.status("UNSUPPORTED_LANGUAGE")
                    continue
                event = {key: item[key] for key in ("generation", "segment_id", "media_start", "media_end")}
                event.update(type="caption.source", session_id=self.session_id, text=text,
                             language="en", final=True, inference_seconds=result["inference_seconds"])
                await self.send(event)
                previous = list(self.history)
                self.history.append(text)
                self.last_caption = {**event, "recent": previous, "queued_at": time.monotonic(), "mode_revision": self.mode_revision}
                if self.mode != "english":
                    await self.enqueue(self.mt_queue, dict(self.last_caption))
            except asyncio.CancelledError:
                raise
            except Exception as error:
                await self.status("MODEL_MISSING" if isinstance(error, FileNotFoundError) else "ASR_FAILED")

    async def mt_worker(self):
        while True:
            item = await self.mt_queue.get()
            if not self.valid(item) or self.mode == "english":
                continue
            try:
                if time.monotonic() - item["queued_at"] > 8:
                    await self.status("TRANSLATION_TIMEOUT")
                    continue
                if self.engine.translator.state != "ready":
                    await self.status("TRANSLATION_LOADING")
                text = await self.engine.translator.translate(item["text"], item["recent"])
                if (not self.valid(item) or self.mode == "english"
                        or item["mode_revision"] != self.mode_revision):
                    continue
                # First model load may be slow; never apply it to a much newer segment.
                if time.monotonic() - item["queued_at"] > 20:
                    await self.status("TRANSLATION_TIMEOUT")
                    continue
                event = {key: item[key] for key in ("session_id", "generation", "segment_id", "media_start", "media_end")}
                await self.send({**event, "type": "caption.translation", "text": text, "language": "zh"})
                await self.status("TRANSLATION_READY")
            except asyncio.CancelledError:
                raise
            except Exception as error:
                await self.status("TRANSLATION_MODEL_MISSING" if isinstance(error, FileNotFoundError)
                                  else "TRANSLATION_TIMEOUT" if isinstance(error, TimeoutError)
                                  else "TRANSLATION_FAILED")

    async def close(self):
        self.active = False
        self.accepting = False
        self.clear()
        self.prefetch_cache.clear()
        if self.engine.active is self:
            self.engine.active = None
        for task in self.tasks:
            task.cancel()
        for task in self.tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
