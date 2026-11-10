"""Silent real-model/real-video integration for prefetch and media-clock scheduling."""
import asyncio
import json
import os
import time
from fractions import Fraction

import av
import httpx
import numpy as np
import soundfile as sf
import uvicorn
from playwright.async_api import async_playwright

from server.app import create_app
from server.config import ROOT, load_config
from server.engine import Engine
from server.media import AudioReader
from scripts.browser_smoke import FIXTURE

os.environ['PLAYWRIGHT_BROWSERS_PATH']=str(ROOT/'runtime/browsers')


def make_video():
    path=ROOT/'work/sync-video-av.mp4'
    if path.exists():return path
    audio,rate=sf.read(ROOT/'work/english-fixture.wav',dtype='float32')
    with av.open(str(path),'w') as output:
        stream=output.add_stream('libx264',rate=30)
        stream.width=1280;stream.height=720;stream.pix_fmt='yuv420p'
        stream.options={'preset':'ultrafast','crf':'28','threads':'1'}
        soundtrack=output.add_stream('aac',rate=rate)
        soundtrack.layout='mono';soundtrack.bit_rate=48000;soundtrack.codec_context.thread_count=1
        audio_cursor=0
        pixels=np.zeros((720,1280,3),dtype=np.uint8)
        pixels[:,:,0]=np.arange(1280,dtype=np.uint16)[None,:]%150+25
        pixels[:,:,1]=45;pixels[:,:,2]=65
        for index in range(int(len(audio)/rate*30)):
            pixels[250:450,:,1]=45
            pixels[250:450,(index*9)%1000:(index*9)%1000+160,1]=150
            frame=av.VideoFrame.from_ndarray(pixels,format='rgb24');frame.pts=index
            for packet in stream.encode(frame):output.mux(packet)
            while audio_cursor<min(len(audio),int((index+1)*rate/30)):
                part=audio[audio_cursor:audio_cursor+1024]
                af=av.AudioFrame.from_ndarray(part.reshape(1,-1),format='fltp',layout='mono')
                af.sample_rate=rate;af.pts=audio_cursor;af.time_base=Fraction(1,rate)
                for packet in soundtrack.encode(af):output.mux(packet)
                audio_cursor+=len(part)
        for packet in stream.encode():output.mux(packet)
        for packet in soundtrack.encode():output.mux(packet)
    return path


async def main():
    config={**load_config(),'port':18775,'translation_port':18776}
    fixture=ROOT/'work/english-fixture.wav'
    engine=Engine(config,media_factory=lambda video:AudioReader(video,local_file=fixture))
    server=uvicorn.Server(uvicorn.Config(create_app(config,engine),host='127.0.0.1',port=18775,log_level='error',access_log=False))
    task=asyncio.create_task(server.serve())
    while not server.started:await asyncio.sleep(.1)
    video=await asyncio.to_thread(make_video)
    html=FIXTURE.replace('ytls_fixture','ytlsFixture').replace('/ytls-test.wav','/ytls-video.mp4').replace('controls loop','controls muted loop')
    report={'source':'controlled_720p_video_with_real_local_models','checks':[]}
    async with async_playwright() as p:
        context=await p.chromium.launch_persistent_context(str(ROOT/f'work/sync-profile-{time.time_ns()}'),channel='chromium',headless=True,
            viewport={'width':1280,'height':900},args=[f'--disable-extensions-except={ROOT/"dist"}',f'--load-extension={ROOT/"dist"}','--mute-audio','--autoplay-policy=no-user-gesture-required'])
        try:
            setup=await context.new_page();await setup.goto('http://127.0.0.1:18775/setup')
            await setup.get_by_role('button',name='连接 Chrome 扩展').click();await setup.get_by_text('配对完成，可以返回 YouTube。').wait_for()
            page=await context.new_page()
            async def route(request):
                if 'ytls-video.mp4' in request.request.url:await request.fulfill(content_type='video/mp4',body=video.read_bytes())
                else:await request.fulfill(content_type='text/html',body=html)
            await page.route('https://www.youtube.com/**',route)
            await page.goto('https://www.youtube.com/watch?v=ytlsFixture')
            await page.get_by_role('button',name='本地字幕',exact=True).click()
            await page.get_by_text('视频字幕：无可用字幕',exact=True).wait_for(timeout=10000)
            await page.get_by_label('字幕显示方式').select_option('bilingual')
            await page.evaluate('document.querySelector("video").play()')
            await asyncio.sleep(3)
            baseline=await page.evaluate('(()=>{const q=document.querySelector("video").getVideoPlaybackQuality();return {total:q.totalVideoFrames,dropped:q.droppedVideoFrames}})()')
            started=time.monotonic()
            await page.get_by_role('button',name='开始本地字幕',exact=True).click()
            await page.get_by_role('button',name='停止本地字幕',exact=True).wait_for()
            report['checks'].append('prefetch_started_without_capture_dialog')
            samples=await page.evaluate('''async () => {
              const v=document.querySelector('video'),results=[];let pauses=0;const paused=()=>pauses++;v.addEventListener('pause',paused);
              const began=performance.now();while(performance.now()-began<30000){const h=document.getElementById('ytls-root'),s=h.shadowRoot;
                results.push({time:v.currentTime,start:Number(h.dataset.cueStart),end:Number(h.dataset.cueEnd),en:s.getElementById('en').textContent.length,zh:s.getElementById('zh').textContent.length,mode:h.dataset.sourceMode});await new Promise(r=>setTimeout(r,100));}
              v.removeEventListener('pause',paused);const q=v.getVideoPlaybackQuality();return {results,pauses,rate:v.playbackRate,quality:{total:q.totalVideoFrames,dropped:q.droppedVideoFrames}};}''')
            visible=[s for s in samples['results'] if s['en'] or s['zh']]
            mismatches=[s for s in visible if s['time']<s['start']-.04 or s['time']>=s['end']+.04]
            assert visible,'No timed subtitles displayed'
            assert any(s['zh'] for s in visible),'No Chinese translation displayed'
            assert not mismatches,mismatches[:2]
            assert samples['pauses']==0 and samples['rate']==1
            async with httpx.AsyncClient(trust_env=False) as client:health=(await client.get('http://127.0.0.1:18775/health')).json()
            assert health['session_source']=='prefetch' and health['session_metrics']['frames']==0
            report.update(elapsed_seconds=round(time.monotonic()-started,2),subtitle_samples=len(visible),mismatched_samples=len(mismatches),automatic_pauses=samples['pauses'],baseline_quality=baseline,final_quality=samples['quality'],metrics=health['session_metrics'])
            report['checks']+=['real_model_prefetch','media_clock_scheduling','no_late_translation_flash','no_forced_pause_or_speed_change','zero_captured_pcm_frames']
            await page.get_by_role('button',name='停止本地字幕',exact=True).click()
            report['checks'].append('stop')
        finally:
            await context.close();server.should_exit=True;await task
            (ROOT/'work/sync-smoke.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
            print(json.dumps(report,ensure_ascii=False),flush=True)


if __name__=='__main__':asyncio.run(main())
