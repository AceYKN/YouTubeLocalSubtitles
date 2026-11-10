import asyncio
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from server.app import create_app
from server.session import Session

CONFIG = {'token':'test-token-not-a-real-secret','extension_id':'a'*32,'port':18765}
ORIGIN = 'chrome-extension://' + CONFIG['extension_id']


class FakeEngine:
    state = 'idle'
    active = None
    def __init__(self):
        self.translator = SimpleNamespace(state='idle',present=lambda:False)
    def present(self): return False
    async def reap_idle(self): await asyncio.Event().wait()
    async def close(self): pass
    def make_vad(self): return object()


def test_health_does_not_expose_pairing_secret():
    with TestClient(create_app(CONFIG,FakeEngine())) as client:
        response=client.get('/health')
        assert response.status_code==200
        assert CONFIG['token'] not in response.text
        assert 'extension_id' not in response.text


@pytest.mark.parametrize('origin,token', [('https://www.youtube.com',CONFIG['token']),(ORIGIN,'wrong'),('',CONFIG['token'])])
def test_websocket_requires_origin_and_token(origin,token):
    engine=FakeEngine()
    with TestClient(create_app(CONFIG,engine)) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect('/v1/session',headers={'origin':origin}) as socket:
                socket.send_json({'type':'hello','token':token})
                socket.receive_json()
        assert engine.active is None


def test_rejects_malformed_control_and_releases_session():
    engine=FakeEngine()
    with TestClient(create_app(CONFIG,engine)) as client:
        with client.websocket_connect('/v1/session',headers={'origin':ORIGIN}) as socket:
            socket.send_json({'type':'hello','token':CONFIG['token']});assert socket.receive_json()['type']=='hello'
            socket.send_json({'type':'session.start','session_id':'s','video_id':'video','generation':1,'mode':'english','active':False})
            assert socket.receive_json()['code']=='READY'
            socket.send_json({'type':'session.reset','video_id':'video','generation':1,'active':False})
            with pytest.raises(WebSocketDisconnect): socket.receive_json()
        assert engine.active is None


def test_stale_asr_result_cannot_cross_seek_boundary():
    async def scenario():
        results=[]
        started=asyncio.Event(); release=asyncio.Event()
        class Socket:
            async def send_json(self,item):results.append(item)
        engine=FakeEngine()
        async def recognize(_):
            started.set(); await release.wait()
            return {'text':'Old video content','language':'en','inference_seconds':0.1}
        engine.recognize=recognize
        session=Session(engine,Socket())
        await session.control({'type':'session.start','session_id':'s','video_id':'video','generation':1,'mode':'english','active':True})
        session.asr_queue.put_nowait({'samples':[],'generation':1,'segment_id':1,'media_start':0,'media_end':1})
        await started.wait()
        await session.control({'type':'session.reset','video_id':'next','generation':2,'active':True})
        release.set();await asyncio.sleep(0.02)
        assert not any(item['type']=='caption.source' for item in results)
        await session.close()
    asyncio.run(scenario())


def test_second_tab_cannot_steal_active_session():
    async def scenario():
        engine=FakeEngine();results=[]
        class Socket:
            async def send_json(self,item):results.append(item)
        first=Session(engine,Socket());second=Session(engine,Socket())
        start={'type':'session.start','session_id':'s','video_id':'video','generation':1,'mode':'english','active':False}
        await first.control(start);await second.control(start)
        assert engine.active is first
        assert results[-1]['code']=='SESSION_BUSY'
        await second.close();assert engine.active is first
        await first.close();assert engine.active is None
    asyncio.run(scenario())
