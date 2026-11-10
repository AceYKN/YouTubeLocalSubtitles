from __future__ import annotations

import asyncio
import contextlib
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
            self.mode = message["mode"]
            self.session_id = message["session_id"]
            await self.reset(message)
            if not self.tasks:
                self.tasks = [asyncio.create_task(self.asr_worker()), asyncio.create_task(self.mt_worker())]
            await self.status("READY")
        elif kind == "session.reset":
            if self.engine.active is self:
                await self.reset(message)
        elif kind == "session.mode":
            if message.get("mode") not in MODES:
                raise ValueError("Invalid mode")
            previous_mode = self.mode
            self.mode = message["mode"]
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
                self.accepting = False
                if self.vad is not None and self.base_media is not None:
                    self.vad.flush()
                    await self.drain_vad()
                self.vad = None
                self.base_media = None
        elif kind == "session.resume":
            if self.engine.active is self and message.get("generation") == self.generation:
                self.active = True
                self.accepting = True
                self.base_media = None
                self.vad = self.engine.make_vad()
        elif kind == "session.stop":
            self.active = False
            self.accepting = False
            self.clear()
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
        self.video_id = video
        self.active = message.get("active") is True
        self.accepting = self.active
        self.clear()
        if self.active:
            self.vad = self.engine.make_vad()

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
        if self.engine.active is self:
            self.engine.active = None
        for task in self.tasks:
            task.cancel()
        for task in self.tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
