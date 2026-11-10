"""Exercise actual public-video audio prefetch without playing sound or saving text."""
import asyncio
import contextlib
import json
import time

import websockets

from server.config import ROOT, load_config


async def main():
    config=load_config();began=time.monotonic();records=[]
    async with websockets.connect(f'ws://127.0.0.1:{config["port"]}/v1/session',origin='chrome-extension://'+config['extension_id']) as socket:
        await socket.send(json.dumps({'type':'hello','token':config['token']}));await socket.recv()
        await socket.send(json.dumps({'type':'session.start','session_id':'real-media-probe','video_id':'aU_fQ5kKFVY','generation':1,'mode':'bilingual','source':'prefetch','active':True,'eligible':True,'playing':True,'media_time':60,'rate':1}))
        async def position():
            while True:
                await socket.send(json.dumps({'type':'session.position','generation':1,'media_time':60+time.monotonic()-began,'rate':1,'playing':True}))
                await asyncio.sleep(.5)
        heartbeat=asyncio.create_task(position())
        try:
            async with asyncio.timeout(70):
                while True:
                    event=json.loads(await socket.recv())
                    if event.get('type') in ('caption.source','caption.translation'):
                        now=60+time.monotonic()-began
                        records.append({'type':event['type'],'start':event['media_start'],'end':event['media_end'],'lead_seconds':round(event['media_start']-now,3),'characters':len(event['text'])})
                    if event.get('code')=='MEDIA_PREFETCH_FAILED':raise RuntimeError('Real media prefetch failed')
                    if sum(r['type']=='caption.translation' for r in records)>=3:break
        finally:
            heartbeat.cancel()
            with contextlib.suppress(asyncio.CancelledError):await heartbeat
    report={'source':'actual_BBC_YouTube_audio','elapsed_seconds':round(time.monotonic()-began,3),'captions':records,'all_ready_before_media_start':all(r['lead_seconds']>=0 for r in records)}
    (ROOT/'work/real-prefetch.json').write_text(json.dumps(report,indent=2),encoding='utf8')
    print(json.dumps(report),flush=True)
    assert report['all_ready_before_media_start']


if __name__=='__main__':asyncio.run(main())
