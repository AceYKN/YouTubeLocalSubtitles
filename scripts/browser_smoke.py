"""Real Chromium extension/capture integration with a controlled YouTube-shaped fixture.

This is not evidence of compatibility with YouTube's current live page internals.
"""
import asyncio
import contextlib
import io
import json
import os
import time

import numpy as np
import soundfile as sf
from playwright.async_api import async_playwright

from server.config import ROOT, ASR_NAME, load_config

os.environ['PLAYWRIGHT_BROWSERS_PATH']=str(ROOT/'runtime/browsers')
FIXTURE='''<!doctype html><html><head><title>YTLocal capture fixture</title><style>
body{margin:0;background:#0c1018;color:white;font:16px system-ui}main{margin:50px auto;width:960px}#movie_player{width:960px;height:540px;position:relative;background:linear-gradient(130deg,#17283c,#0a101c);border-radius:14px;overflow:hidden}video{width:100%;height:100%}.title{position:absolute;top:50px;left:40px;font-size:32px;pointer-events:none}.sub{font-size:16px;color:#a3b4ca}</style></head><body><main><h2>Local subtitle integration fixture</h2><div id="movie_player"><video class="html5-main-video" controls loop src="/ytls-test.wav"></video><div class="title">Local speech recognition<br><span class="sub">Controlled audio fixture · English / 中文 / 双语</span></div><button class="ytp-subtitles-button" style="display:none">CC</button></div></main><script>
window.testHasCaptions=false;window.addEventListener('message',e=>{if(e.data?.source==='ytls:player')window.lastPlayerState=e.data.state});const p=document.getElementById('movie_player');p.getPlayerResponse=()=>({videoDetails:{videoId:'ytls_fixture'},playabilityStatus:{status:'OK'},streamingData:{formats:[]},...(window.testHasCaptions?{captions:{playerCaptionsTracklistRenderer:{captionTracks:[{kind:'asr',languageCode:'en'}]}}}:{})});p.getOption=()=>window.testHasCaptions?[{languageCode:'en'}]:[];
</script></body></html>'''


async def mute_test_browser(page):
    """Mute only this test process tree at the Windows mixer, before playback.

    Chromium --mute-audio also zeros tab capture, so initialize an exactly silent
    oscillator, find its owned WASAPI session and mute it. Never play if unverified.
    """
    import psutil
    from pycaw.pycaw import AudioUtilities
    profile=str(ROOT/'work/browser-profile').lower().replace('\\','/')
    roots=[]
    for process in psutil.process_iter(['pid','name','cmdline']):
        try:
            command=' '.join(process.info['cmdline'] or []).lower().replace('\\','/')
            if process.info['name']=='chrome.exe' and profile in command and '--type=' not in command:
                roots.append(process)
        except (psutil.NoSuchProcess,psutil.AccessDenied):pass
    owned=set()
    for process in roots:
        owned.add(process.pid);owned.update(child.pid for child in process.children(recursive=True))
    if not owned:raise RuntimeError('Cannot identify test browser. Audio playback refused.')
    await page.evaluate('''async () => { const c=new AudioContext();const g=c.createGain();g.gain.value=0;const o=c.createOscillator();o.connect(g).connect(c.destination);o.start();await c.resume();window.silentTestContext={c,g,o}; }''')
    for _ in range(30):
        for session in AudioUtilities.GetAllSessions():
            if session.ProcessId in owned:
                session.SimpleAudioVolume.SetMute(1,None)
                if session.SimpleAudioVolume.GetMute():return
        await asyncio.sleep(0.2)
        for process in roots:
            with contextlib.suppress(psutil.NoSuchProcess):
                owned.update(child.pid for child in process.children(recursive=True))
    raise RuntimeError('Cannot verify test browser mute. Audio playback refused.')


async def main():
    config=load_config()
    if not (ROOT/'work/english-fixture.wav').exists():
        import subprocess
        subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(ROOT/'scripts/Make-TestAudio.ps1')],check=True,creationflags=subprocess.CREATE_NO_WINDOW)
    samples,rate=sf.read(ROOT/'work/english-fixture.wav',dtype='float32')
    # Add silence between excerpts so VAD produces stable, testable boundaries.
    clip=np.concatenate([samples,np.zeros(rate,dtype=np.float32)])
    wav=io.BytesIO();sf.write(wav,np.tile(clip,3),rate,format='WAV',subtype='PCM_16')
    report={'fixture_only':True,'checks':[]}
    errors=[]
    async with async_playwright() as playwright:
        context=await playwright.chromium.launch_persistent_context(
            # Fresh profile is essential: unpacked content scripts refresh from
            # disk while Chrome can retain an old extension service worker.
            str(ROOT/f'work/browser-profile-{time.time_ns()}'),channel='chromium',headless=True,viewport={'width':1280,'height':900},
            args=[f'--disable-extensions-except={ROOT / "dist"}',f'--load-extension={ROOT / "dist"}',
                  '--auto-accept-this-tab-capture','--autoplay-policy=no-user-gesture-required'],
            ignore_default_args=['--mute-audio'],
        )
        try:
            worker=context.service_workers[0] if context.service_workers else await context.wait_for_event('serviceworker',timeout=15000)
            report['extension_id']=worker.url.split('/')[2]
            assert report['extension_id']==config['extension_id']
            report['checks'].append('extension_loaded')
            setup=await context.new_page();await setup.goto(f'http://127.0.0.1:{config["port"]}/setup')
            await setup.get_by_role('button',name='连接 Chrome 扩展').click()
            await setup.get_by_text('配对完成，可以返回 YouTube。').wait_for(timeout=10000)
            report['checks'].append('local_pairing')
            page=await context.new_page()
            page.on('pageerror',lambda error:errors.append(str(error)))
            page.on('console',lambda message:errors.append(message.text) if message.type=='error' else None)
            async def route(request):
                if 'ytls-test.wav' in request.request.url:
                    await request.fulfill(content_type='audio/wav',body=wav.getvalue())
                else:await request.fulfill(content_type='text/html',body=FIXTURE)
            await page.route('https://www.youtube.com/**',route)
            await page.goto('https://www.youtube.com/watch?v=ytls_fixture')
            await page.get_by_role('button',name='本地字幕',exact=True).click()
            await page.get_by_text('视频字幕：无可用字幕',exact=True).wait_for(timeout=10000)
            await page.get_by_label('字幕显示方式').select_option('bilingual')
            report['checks'].append('no_caption_detection')
            await mute_test_browser(page)
            report['checks'].append('test_browser_os_mute_verified_before_playback')
            started=time.monotonic()
            await page.get_by_role('button',name='开始本地字幕',exact=True).click()
            await page.get_by_role('button',name='停止本地字幕',exact=True).wait_for(timeout=15000)
            report['checks'].append('page_button_capture')
            await page.evaluate('document.querySelector("video").play()')
            await asyncio.sleep(5)
            import httpx
            health=httpx.get(f'http://127.0.0.1:{config["port"]}/health',trust_env=False).json()
            if not health.get('session_metrics',{}).get('frames',0):raise RuntimeError('No PCM frames reached service after playback started')
            await page.locator('#ytls-root').locator('#en').filter(has_text='').wait_for(state='visible',timeout=45000)
            await page.wait_for_function('document.querySelector("#ytls-root")?.shadowRoot?.querySelector("#en")?.textContent.length > 3',timeout=45000)
            report['first_source_seconds']=round(time.monotonic()-started,2)
            report['checks'].append('real_pcm_asr')
            await page.wait_for_function('document.querySelector("#ytls-root")?.shadowRoot?.querySelector("#zh")?.textContent.length > 1',timeout=45000)
            report['first_bilingual_seconds']=round(time.monotonic()-started,2)
            report['checks'].append('real_local_translation')
            folder=ROOT/'output/playwright';folder.mkdir(parents=True,exist_ok=True)
            await page.screenshot(path=str(folder/'bilingual-fixture.png'))
            await page.get_by_label('字幕显示方式').select_option('chinese')
            assert await page.locator('#ytls-root').locator('#en').is_hidden()
            await page.get_by_label('字幕显示方式').select_option('english')
            assert await page.locator('#ytls-root').locator('#zh').is_hidden()
            await page.get_by_label('字幕显示方式').select_option('bilingual')
            report['checks'].append('three_display_modes')
            await page.evaluate('document.querySelector("video").pause()')
            for _ in range(20):
                await asyncio.sleep(.1)
                if not httpx.get(f'http://127.0.0.1:{config["port"]}/health',trust_env=False).json()['receiving_audio']:break
            else:raise AssertionError('Audio still accepted after pause')
            await page.evaluate('document.querySelector("video").play()')
            for _ in range(20):
                await asyncio.sleep(.1)
                if httpx.get(f'http://127.0.0.1:{config["port"]}/health',trust_env=False).json()['receiving_audio']:break
            else:raise AssertionError('Audio did not resume')
            report['checks'].append('pause_resume_protocol')
            old_generation=await page.locator('#ytls-root').get_attribute('data-generation')
            await page.evaluate('document.querySelector("video").currentTime=1')
            await page.wait_for_function('(previous)=>document.getElementById("ytls-root").dataset.generation!==previous',arg=old_generation)
            report['checks'].append('seek_invalidates_generation')
            await page.locator('#movie_player').evaluate('(player)=>player.requestFullscreen()')
            assert await page.evaluate('document.fullscreenElement?.id')=='movie_player'
            assert await page.get_by_role('button',name='本地字幕',exact=True).is_visible()
            await page.evaluate('document.exitFullscreen()')
            report['checks'].append('fullscreen_controls')
            await page.evaluate('document.getElementById("movie_player").classList.add("ad-showing")')
            await page.get_by_text('广告期间暂停识别',exact=True).wait_for(timeout=5000)
            await page.evaluate('document.getElementById("movie_player").classList.remove("ad-showing")')
            report['checks'].append('ad_suppression')
            await page.evaluate('window.testHasCaptions=true')
            await page.get_by_text('视频字幕：已有字幕，默认不识别',exact=True).wait_for(timeout=5000)
            await page.wait_for_function('!document.querySelector("#ytls-root")?.shadowRoot?.querySelector("#en")?.textContent',timeout=5000)
            report['checks'].append('native_caption_takeover_clears_local')
            await page.get_by_label('字幕显示方式').select_option('english')
            await page.get_by_role('button',name='停止本地字幕',exact=True).click()
            await page.get_by_role('button',name='开始本地字幕',exact=True).wait_for()
            report['checks'].append('stop_releases_capture')
            report['console_errors']=errors
        except Exception:
            report['console_errors']=errors
            report['transport']=await worker.evaluate("chrome.runtime.sendMessage({target:'offscreen',type:'diagnostics'})")
            for page in context.pages:
                try:
                    if 'youtube.com' in page.url:
                        report['failure_status']=await page.locator('#ytls-root').locator('#status').text_content(timeout=2000)
                        report['failure_player']=await page.evaluate('({bridge:window.lastPlayerState,extension:document.getElementById("ytls-root").dataset,paused:document.querySelector("video").paused,time:document.querySelector("video").currentTime,ready:document.querySelector("video").readyState})')
                        import httpx
                        report['service_health']=httpx.get(f'http://127.0.0.1:{config["port"]}/health',trust_env=False).json()
                        folder=ROOT/'output/playwright';folder.mkdir(parents=True,exist_ok=True)
                        await page.screenshot(path=str(folder/'failure.png'))
                except Exception:pass
            raise
        finally:
            folder=ROOT/'work';folder.mkdir(exist_ok=True)
            (folder/'browser-smoke.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps(report,ensure_ascii=False),flush=True)
            await context.close()


if __name__=='__main__':asyncio.run(main())
