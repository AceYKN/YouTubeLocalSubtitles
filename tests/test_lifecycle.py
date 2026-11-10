import asyncio
from types import SimpleNamespace

from server.engine import Translator
from server.session import Session
from tests.test_service import FakeEngine


def test_pause_allows_already_spoken_segment_to_finish():
    async def scenario():
        results=[];started=asyncio.Event();release=asyncio.Event()
        class Socket:
            async def send_json(self,item):results.append(item)
        engine=FakeEngine()
        async def recognize(_):
            started.set();await release.wait()
            return {'text':'The sentence before pausing.','language':'en','inference_seconds':0.1}
        engine.recognize=recognize
        session=Session(engine,Socket())
        await session.control({'type':'session.start','session_id':'s','video_id':'v','generation':1,'mode':'english','active':True})
        session.asr_queue.put_nowait({'samples':[],'generation':1,'segment_id':1,'media_start':0,'media_end':1})
        await started.wait();await session.control({'type':'session.pause','generation':1})
        assert not session.accepting
        release.set();await asyncio.sleep(0.02)
        assert any(item.get('text')=='The sentence before pausing.' for item in results)
        await session.close()
    asyncio.run(scenario())


def test_switching_to_english_discards_inflight_translation():
    async def scenario():
        results=[];started=asyncio.Event();release=asyncio.Event()
        class Socket:
            async def send_json(self,item):results.append(item)
        engine=FakeEngine()
        async def recognize(_):return {'text':'Current subtitle.','language':'en','inference_seconds':0.1}
        async def translate(*_):started.set();await release.wait();return '当前字幕。'
        engine.recognize=recognize
        engine.translator=SimpleNamespace(state='ready',translate=translate)
        session=Session(engine,Socket())
        await session.control({'type':'session.start','session_id':'s','video_id':'v','generation':1,'mode':'bilingual','active':True})
        session.asr_queue.put_nowait({'samples':[],'generation':1,'segment_id':1,'media_start':0,'media_end':1})
        await started.wait();await session.control({'type':'session.mode','mode':'english'})
        release.set();await asyncio.sleep(0.02)
        assert not any(item['type']=='caption.translation' for item in results)
        await session.close()
    asyncio.run(scenario())


def test_canceled_model_load_reuses_owned_process(monkeypatch):
    async def scenario():
        translator=Translator({'token':'test','translation_port':18766})
        translator.process=SimpleNamespace(returncode=None)
        translator.state='loading'
        monkeypatch.setattr(translator,'present',lambda:True)
        class Client:
            def __init__(self,**kwargs):pass
            async def __aenter__(self):return self
            async def __aexit__(self,*args):pass
            async def get(self,*args):return SimpleNamespace(status_code=200)
        async def forbidden_spawn(*args,**kwargs):raise AssertionError('Duplicated model process')
        monkeypatch.setattr('server.engine.httpx.AsyncClient',Client)
        monkeypatch.setattr('server.engine.asyncio.create_subprocess_exec',forbidden_spawn)
        await translator.ensure_ready()
        assert translator.state=='ready'
    asyncio.run(scenario())


def test_english_to_chinese_translates_current_caption_without_redecoding():
    async def scenario():
        source=asyncio.Event();translated=asyncio.Event();results=[];calls={'asr':0,'mt':0}
        class Socket:
            async def send_json(self,item):
                results.append(item)
                if item['type']=='caption.source':source.set()
                if item['type']=='caption.translation':translated.set()
        engine=FakeEngine()
        async def recognize(_):
            calls['asr']+=1
            return {'text':'Current English caption.','language':'en','inference_seconds':0.1}
        async def translate(*_):calls['mt']+=1;return '当前中文字幕。'
        engine.recognize=recognize;engine.translator=SimpleNamespace(state='ready',translate=translate)
        session=Session(engine,Socket())
        await session.control({'type':'session.start','session_id':'s','video_id':'v','generation':1,'mode':'english','active':True})
        session.asr_queue.put_nowait({'samples':[],'generation':1,'segment_id':1,'media_start':0,'media_end':1})
        await asyncio.wait_for(source.wait(),1)
        assert calls=={'asr':1,'mt':0}
        await session.control({'type':'session.mode','mode':'chinese'})
        await asyncio.wait_for(translated.wait(),1)
        assert calls=={'asr':1,'mt':1}
        await session.close()
    asyncio.run(scenario())
