from __future__ import annotations

import asyncio
import contextlib
import json
import secrets
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .config import load_config
from .engine import Engine
from .session import Session


def create_app(config=None, engine=None):
    config = config or load_config()
    engine = engine or Engine(config)

    @asynccontextmanager
    async def lifespan(app):
        reaper = asyncio.create_task(engine.reap_idle())
        try:
            yield
        finally:
            reaper.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await reaper
            await engine.close()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])

    @app.get("/health")
    async def health():
        return {"version": "0.1.0", "asr": engine.state,
                "models_present": engine.present(), "translation": engine.translator.state,
                "translation_present": engine.translator.present(),
                "session_metrics": getattr(engine.active, "metrics", None),
                "receiving_audio": getattr(engine.active, "accepting", False)}

    @app.get("/setup", response_class=HTMLResponse)
    async def setup():
        nonce = secrets.token_urlsafe(16)
        payload = json.dumps({"type": "pair", "token": config["token"], "port": config["port"]})
        extension = json.dumps(config["extension_id"])
        html = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>本地字幕设置</title>
<style>body{{font:16px system-ui;max-width:760px;margin:70px auto;padding:24px;background:#11151e;color:#e4e9f4;line-height:1.8}}button{{padding:12px 24px;background:#79aaff;border:0;border-radius:8px;font-size:16px;cursor:pointer}}code{{color:#a9c8ff}}a{{color:#a9c8ff}}</style>
<h1>YouTube 本地字幕</h1><p>本机服务已启动。模型加载和字幕翻译均在这台电脑运行。</p>
<ol><li>打开 <code>chrome://extensions</code>，开启开发者模式。</li><li>选择“加载已解压的扩展程序”，选择项目中的 <code>dist</code> 文件夹。</li><li>点击下面按钮完成配对，然后刷新 YouTube 页面。</li></ol>
<button id="pair">连接 Chrome 扩展</button><p id="result"></p>
<p>使用：在播放器旁点击“本地字幕”，选择英文、中文或双语。开始时在 Chrome 弹窗选择当前标签页并共享音频。</p>
<script nonce="{nonce}">document.getElementById('pair').onclick=()=>{{const out=document.getElementById('result');if(!globalThis.chrome?.runtime?.sendMessage){{out.textContent='请先在 Chrome 中加载扩展，再刷新本页。';return;}}chrome.runtime.sendMessage({extension},{payload},r=>{{out.textContent=chrome.runtime.lastError?'未找到扩展，请检查 dist 是否已加载并刷新本页。':r?.ok?'配对完成，可以返回 YouTube。':'连接失败，请重试。';}});}};</script></html>'''
        return HTMLResponse(html, headers={"Cache-Control": "no-store", "X-Frame-Options": "DENY",
            "Content-Security-Policy": f"default-src 'none'; style-src 'unsafe-inline'; script-src 'nonce-{nonce}'; frame-ancestors 'none'"})

    @app.websocket("/v1/session")
    async def websocket_endpoint(websocket: WebSocket):
        if websocket.headers.get("origin") != "chrome-extension://" + config["extension_id"]:
            await websocket.close(code=1008)
            return
        await websocket.accept()
        session = None
        try:
            raw = await asyncio.wait_for(websocket.receive_text(), timeout=5)
            if len(raw) > 4096:
                raise ValueError("Invalid hello")
            hello = json.loads(raw)
            if not isinstance(hello, dict):
                raise ValueError("Invalid hello")
            token = hello.get("token", "")
            if hello.get("type") != "hello" or not isinstance(token, str) or not secrets.compare_digest(token, config["token"]):
                await websocket.close(code=1008)
                return
            session = Session(engine, websocket)
            await websocket.send_json({"type": "hello", "version": "0.1.0"})
            while True:
                message = await websocket.receive()
                if message["type"] == "websocket.disconnect":
                    break
                if message.get("bytes") is not None:
                    await session.audio(message["bytes"])
                elif message.get("text") is not None:
                    if len(message["text"]) > 8192:
                        raise ValueError("Control message too large")
                    control = json.loads(message["text"])
                    if not isinstance(control, dict):
                        raise ValueError("Invalid control")
                    await session.control(control)
        except (WebSocketDisconnect, RuntimeError):
            pass
        except FileNotFoundError:
            with contextlib.suppress(Exception):
                await websocket.send_json({"type": "status", "code": "MODEL_MISSING"})
                await websocket.close(code=1011)
        except (ValueError, TypeError, KeyError, TimeoutError):
            with contextlib.suppress(Exception):
                await websocket.close(code=1008)
        finally:
            if session:
                await session.close()

    app.state.engine = engine
    return app
