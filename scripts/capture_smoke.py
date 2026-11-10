"""Verify compatibility audio survives video-track release, without model load."""
import asyncio
import json
import os
import time
from types import SimpleNamespace

import httpx
import uvicorn
from playwright.async_api import async_playwright

from server.app import create_app
from server.config import ROOT,load_config
from scripts.browser_smoke import FIXTURE,mute_test_browser

os.environ['PLAYWRIGHT_BROWSERS_PATH']=str(ROOT/'runtime/browsers')


class Vad:
    def accept_waveform(self,samples):pass
    def empty(self):return True
    def flush(self):pass


class CaptureEngine:
    state='ready'
    active=None
    translator=SimpleNamespace(state='idle',present=lambda:False)
    def present(self):return True
    def make_vad(self):return Vad()
    async def reap_idle(self):await asyncio.Event().wait()
    async def close(self):pass


async def main():
    config={**load_config(),'port':18775}
    server=uvicorn.Server(uvicorn.Config(create_app(config,CaptureEngine()),host='127.0.0.1',port=18775,log_level='error',access_log=False))
    task=asyncio.create_task(server.serve())
    while not server.started:await asyncio.sleep(.1)
    async with async_playwright() as p:
        context=await p.chromium.launch_persistent_context(str(ROOT/f'work/browser-profile-capture-{time.time_ns()}'),channel='chromium',headless=True,
            args=[f'--disable-extensions-except={ROOT/"dist"}',f'--load-extension={ROOT/"dist"}','--auto-accept-this-tab-capture','--autoplay-policy=no-user-gesture-required'],ignore_default_args=['--mute-audio'])
        try:
            setup=await context.new_page();await setup.goto('http://127.0.0.1:18775/setup')
            await setup.get_by_role('button',name='连接 Chrome 扩展').click();await setup.get_by_text('配对完成，可以返回 YouTube。').wait_for()
            page=await context.new_page()
            async def route(request):
                if 'ytls-test.wav' in request.request.url:await request.fulfill(content_type='audio/wav',body=(ROOT/'work/english-fixture.wav').read_bytes())
                else:await request.fulfill(content_type='text/html',body=FIXTURE)
            await page.route('https://www.youtube.com/**',route)
            await page.goto('https://www.youtube.com/watch?v=ytls_fixture')
            await page.get_by_role('button',name='本地字幕',exact=True).click()
            await page.get_by_text('视频字幕：无可用字幕',exact=True).wait_for(timeout=10000)
            await mute_test_browser(page)
            await page.get_by_text('兼容方式',exact=True).click()
            await page.get_by_role('button',name='兼容音频采集（字幕有延迟）',exact=True).click()
            await page.get_by_role('button',name='停止本地字幕',exact=True).wait_for(timeout=15000)
            assert await page.locator('#ytls-root').get_attribute('data-video-capture')=='stopped'
            await page.evaluate('document.querySelector("video").play()')
            await asyncio.sleep(3)
            async with httpx.AsyncClient(trust_env=False) as client:health=(await client.get('http://127.0.0.1:18775/health')).json()
            assert health['session_source']=='live' and health['session_metrics']['frames']>10 and health['session_metrics']['peak']>.01
            await page.get_by_role('button',name='停止本地字幕',exact=True).click()
            report={'video_track_stopped':True,'audio_continued':True,'frames':health['session_metrics']['frames'],'peak':health['session_metrics']['peak'],'models_used':False,'system_mute_verified':True}
            (ROOT/'work/capture-smoke.json').write_text(json.dumps(report),encoding='utf8')
            print(json.dumps(report),flush=True)
        finally:await context.close();server.should_exit=True;await task


if __name__=='__main__':asyncio.run(main())
