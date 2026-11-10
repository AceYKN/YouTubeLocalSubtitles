import asyncio
from types import SimpleNamespace

import numpy as np

from server.session import Session
from tests.test_service import FakeEngine


def test_prefetch_generates_future_cues_without_capturing_or_controlling_playback():
    async def scenario():
        messages=[];ready=asyncio.Event()
        class Socket:
            async def send_json(self,event):
                messages.append(event)
                if event['type']=='caption.translation':ready.set()
        class Reader:
            duration=60
            def __init__(self,video):pass
            def open(self):pass
            def close(self):pass
            def read(self,start,duration):return start,np.ones(int(duration*16000),dtype=np.float32)*0.1
        engine=FakeEngine();engine.media_factory=Reader
        async def prepare():pass
        async def recognize(samples):return {'text':'Prepared subtitle.','language':'en','inference_seconds':0.1}
        async def translate(*args):return '提前生成的字幕。'
        engine.prepare=prepare;engine.recognize=recognize
        engine.translator=SimpleNamespace(state='ready',ensure_ready=prepare,translate=translate)
        session=Session(engine,Socket())
        try:
            await session.control({'type':'session.start','session_id':'s','video_id':'abcdefghijk','generation':1,'mode':'bilingual','source':'prefetch','active':False,'eligible':True,'playing':False,'media_time':0,'rate':1})
            await asyncio.wait_for(ready.wait(),3)
            cues=[m for m in messages if m['type']=='caption.source']
            assert cues and cues[0]['media_start']>=4
            assert not session.accepting and session.vad is None
            assert session.media_position==0 and not session.playing
            assert not any(m.get('type') in ('video.pause','video.seek') for m in messages)
            await session.control({'type':'session.reset','generation':2,'video_id':'abcdefghijk','active':True,'eligible':True,'media_time':0,'playing':False,'rate':1})
            await asyncio.sleep(.35)
            assert any(m['type']=='caption.source' and m['generation']==2 for m in messages)
        finally:await session.close()
    asyncio.run(scenario())
