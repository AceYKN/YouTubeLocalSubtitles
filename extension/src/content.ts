import {makeAudioGraph, shouldRecognize, type HandleTrack, type Mode, type PlayerState} from './common';

let state: PlayerState | null = null;
let previousState: PlayerState | null = null;
let previousWall = 0;
let mode: Mode = 'bilingual';
let force = false;
let paired = false;
let capturing = false;
let starting = false;
let active = false;
let generation = 1;
let sequence = 0;
let stream: MediaStream | null = null;
let graph: Awaited<ReturnType<typeof makeAudioGraph>> | null = null;
let host: HTMLElement | null = null;
let shadow: ShadowRoot | null = null;
let statusText = '检测视频字幕…';
let caption: {id:number;generation:number;en:string;zh:string;shown:number} | null = null;
let hideNativeStyle: HTMLStyleElement | null = null;
let lastVideo = '';
let audioFrames=0;
let forwardedFrames=0;

const labels: Record<string,string> = {
  READY:'已连接，等待视频语音', RECOGNIZING:'正在识别', TRANSLATION_LOADING:'正在加载中文翻译模型，英文字幕可先显示',
  MODE_CHANGED:'字幕模式已切换', MODEL_MISSING:'识别模型尚未就绪，请先运行模型安装脚本',
  TRANSLATION_MODEL_MISSING:'翻译模型尚未就绪，可先使用英文模式', ASR_FAILED:'识别失败，请查看本机服务诊断',
  TRANSLATION_FAILED:'翻译暂不可用，可切换英文模式', TRANSLATION_TIMEOUT:'翻译暂时跟不上，已跳过过期内容',
  QUEUE_OVERFLOW:'字幕暂时跟不上，正在跳过积压内容', SERVICE_DISCONNECTED:'本机服务连接已断开，请重新开始',
  SESSION_BUSY:'另一个标签页正在识别，请先停止那个会话', UNSUPPORTED_LANGUAGE:'检测到非英语内容，第一版尚未完成该语言验证',
  CAPTURE_FAILED:'音频获取失败，可以从页面按钮重新开始',
};

async function request(message: any): Promise<any> {
  return chrome.runtime.sendMessage({target:'background',...message});
}
function setStatus(text: string) { statusText=text; render(); }
function session() {
  return {session_id:crypto.randomUUID(),video_id:state!.videoId,generation,mode,active:shouldRecognize(state,force),rate:state!.rate,media_time:state!.time};
}
function clearCaption() { caption=null; renderCaption(); }
function reset(reason='manual') {
  generation++; sequence=0; clearCaption();
  active = capturing && shouldRecognize(state,force);
  if (capturing && state) void request({type:'reset',state:{generation,video_id:state.videoId,active,rate:state.rate,media_time:state.time,reason}}).catch(() => stopLocal('扩展已重新加载，请刷新页面'));
  render();
}
async function stopLocal(reason='本地字幕已停止', notify=true) {
  capturing=false; starting=false; active=false; generation++; sequence=0;
  if (graph) { const old=graph; graph=null; await old.close().catch(() => undefined); }
  const old=stream; stream=null; old?.getTracks().forEach(track => track.stop());
  if (notify) await request({type:'stop'}).catch(() => undefined);
  clearCaption(); setStatus(reason);
}
function eligible() {
  if (!paired) { setStatus('请先打开本机设置页，连接 Chrome 扩展'); return false; }
  if (!state?.videoId) { setStatus('请先打开普通 YouTube 视频'); return false; }
  if (!force && state.captions !== 'absent') {
    setStatus(state.captions === 'present' ? '视频已有字幕，默认使用 YouTube 字幕。需要时可勾选强制识别。' : '字幕状态尚未确定，稍等后重试，或勾选强制识别。');
    return false;
  }
  return true;
}
async function startPageCapture() {
  if (starting || capturing || !eligible()) return;
  starting=true; generation++; setStatus('请选择当前 YouTube 标签页，并开启共享音频');
  try {
    // Keep this invocation in the original click activation, before any awaited request.
    const captured = await navigator.mediaDevices.getDisplayMedia({
      video:true, audio:{suppressLocalAudioPlayback:false} as any,
      preferCurrentTab:true, selfBrowserSurface:'include', surfaceSwitching:'exclude',
    } as DisplayMediaStreamOptions);
    stream=captured;
    const track=captured.getVideoTracks()[0] as HandleTrack;
    const handle=track?.getCaptureHandle?.();
    if (!handle || handle.handle !== state?.handle || handle.origin !== location.origin) throw new Error('请选择当前 YouTube 标签页。无法核对共享目标时，可用 Alt+Shift+L 定向启动。');
    if (!captured.getAudioTracks().length) throw new Error('未获取音频，请选择当前标签页并勾选“共享标签页音频”');
    captured.getTracks().forEach(t => t.addEventListener('ended', () => { if (capturing || starting) void stopLocal('Chrome 已停止共享'); }));
    const result=await request({type:'connect',session:session()});
    if (!result?.ok) throw new Error(result?.error || '无法连接本机服务');
    capturing=true; active=shouldRecognize(state,force); sequence=0;
    graph=await makeAudioGraph(captured, data => {
      audioFrames++;if(host)host.dataset.audioFrames=String(audioFrames);
      if (!capturing || !active || !state) return;
      const video=document.querySelector<HTMLVideoElement>('video.html5-main-video');
      if (!video || video.paused || video.seeking) return;
      forwardedFrames++;if(host)host.dataset.forwardedFrames=String(forwardedFrames);
      void request({type:'audio',data,generation,sequence:sequence++,media_start:Math.max(0,video.currentTime-0.1*video.playbackRate),rate:video.playbackRate}).then(result=>{if(!result?.ok)void stopLocal(result?.error||'扩展连接已断开');}).catch(() => stopLocal('扩展连接已断开'));
    });
    starting=false; reset('capture-ready'); setStatus(active?'正在等待语音…':'已授权，等待无字幕视频播放');
  } catch (error) {
    const value=error as Error;
    await stopLocal(value.name === 'NotAllowedError' ? '已取消共享，可随时重新开始' : value.message || '无法获取音频');
  }
}

function renderCaption() {
  if (!shadow) return;
  const en=shadow.querySelector<HTMLElement>('#en')!;
  const zh=shadow.querySelector<HTMLElement>('#zh')!;
  const fresh=caption && caption.generation===generation && performance.now()-caption.shown<8000;
  en.textContent=fresh && mode!=='chinese'?caption!.en:'';
  zh.textContent=fresh && mode!=='english'?(caption!.zh || (mode==='chinese'?'正在翻译…':'')):'';
  en.hidden=!en.textContent; zh.hidden=!zh.textContent;
}
function render() {
  if (!shadow) return;
  if(host){host.dataset.generation=String(generation);host.dataset.active=String(active);host.dataset.capturing=String(capturing);}
  const status=shadow.querySelector<HTMLElement>('#status')!;
  status.textContent=statusText;
  shadow.querySelector<HTMLElement>('#native')!.textContent='视频字幕：'+({present:'已有字幕，默认不识别',absent:'无可用字幕',unknown:'正在检测 / 无法确定'}[state?.captions || 'unknown']);
  const start=shadow.querySelector<HTMLButtonElement>('#start')!;
  start.disabled=starting; start.textContent=starting?'正在连接…':capturing?'停止本地字幕':'开始本地字幕';
  shadow.querySelector<HTMLSelectElement>('#mode')!.value=mode;
  shadow.querySelector<HTMLInputElement>('#force')!.checked=force;
  shadow.querySelector<HTMLElement>('#dot')!.style.background=capturing?(active?'#8be9ba':'#f5d790'):'#a6abb7';
  if (hideNativeStyle) hideNativeStyle.disabled=!(capturing && force);
  renderCaption();
}
function mount() {
  const player=document.getElementById('movie_player');
  const isWatch=location.pathname==='/watch';
  if (!player || !isWatch) { if (capturing) void stopLocal('已离开视频页面'); host?.remove(); host=null; shadow=null; return; }
  if (host?.isConnected && host.parentElement===player) return;
  host?.remove();
  host=document.createElement('div'); host.id='ytls-root';
  host.style.cssText='position:absolute;inset:0;z-index:64;pointer-events:none';
  shadow=host.attachShadow({mode:'open'});
  shadow.innerHTML=`<style>
    :host{font:14px system-ui;color:#f3f5fa}*{box-sizing:border-box}button,select{font:inherit}button{cursor:pointer;border:1px solid #ffffff35;background:#202631;color:#f4f6fa;border-radius:9px;padding:9px 13px}button:hover{background:#30394a}button:disabled{opacity:.6;cursor:wait}
    #toggle{position:absolute;right:16px;top:16px;pointer-events:auto;background:#141923d9;display:flex;align-items:center;gap:7px;box-shadow:0 3px 16px #0004}#dot{width:7px;height:7px;border-radius:50%}
    #panel{position:absolute;top:61px;right:16px;width:min(310px,85vw);pointer-events:auto;background:#121823f5;border:1px solid #ffffff28;border-radius:13px;padding:17px;box-shadow:0 12px 40px #0006;line-height:1.7}#panel[hidden]{display:none}h3{font-size:16px;margin:0 0 10px}p{margin:9px 0;color:#c6cedd}#status{font-size:13px;overflow-wrap:anywhere;min-height:34px}select{width:100%;padding:8px;border-radius:7px;background:#252e3e;border:1px solid #ffffff35;color:white}label{display:block;margin:12px 0;color:#d1d8e6;font-size:12px}#start{width:100%;background:#9bbdf8;color:#132039;border:0;font-weight:600}#setup{width:100%;margin-top:9px;background:transparent;font-size:12px}.hint{font-size:11px;color:#929fb5}
    #captions{position:absolute;bottom:85px;left:5%;width:90%;text-align:center;pointer-events:none;display:flex;align-items:center;flex-direction:column;gap:4px;font:500 clamp(16px,2vw,26px)/1.5 system-ui;text-shadow:0 1px 3px #000,0 1px 8px #000}#captions div{max-width:100%;padding:0 8px;border-radius:3px;background:#000a;white-space:pre-wrap;overflow-wrap:anywhere;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}#captions div[hidden]{display:none}#zh{color:#f1f5ff}
  </style><button id="toggle" aria-label="本地字幕" aria-expanded="false"><span id="dot"></span>本地字幕</button>
  <section id="panel" hidden aria-label="本地字幕设置"><h3>本地字幕</h3><p id="native"></p><select id="mode" aria-label="字幕显示方式"><option value="english">英文</option><option value="chinese">中文</option><option value="bilingual">双语</option></select>
  <label><input id="force" type="checkbox"> 已有字幕或无法判断时，仍使用本地识别</label><p id="status" role="status"></p><button id="start">开始本地字幕</button><button id="setup">打开本机设置页</button><p class="hint">声音只在本机处理。备用快捷键 Alt + Shift + L</p></section>
  <div id="captions" aria-live="off"><div id="en" hidden></div><div id="zh" hidden></div></div>`;
  player.append(host);
  hideNativeStyle?.remove(); hideNativeStyle=document.createElement('style');
  hideNativeStyle.textContent='#movie_player .ytp-caption-window-container{visibility:hidden!important}';
  hideNativeStyle.disabled=true; document.documentElement.append(hideNativeStyle);
  const panel=shadow.querySelector<HTMLElement>('#panel')!;
  shadow.querySelector<HTMLButtonElement>('#toggle')!.onclick=()=>{panel.hidden=!panel.hidden;shadow!.querySelector('#toggle')!.setAttribute('aria-expanded',String(!panel.hidden));};
  shadow.querySelector<HTMLButtonElement>('#start')!.onclick=()=>{if(capturing) void stopLocal(); else void startPageCapture();};
  shadow.querySelector<HTMLButtonElement>('#setup')!.onclick=()=>{window.open('http://127.0.0.1:18765/setup','_blank','noopener');};
  shadow.querySelector<HTMLSelectElement>('#mode')!.onchange=event=>{
    mode=(event.target as HTMLSelectElement).value as Mode;
    void request({type:'mode',mode}).catch(()=>undefined); render();
  };
  shadow.querySelector<HTMLInputElement>('#force')!.onchange=event=>{force=(event.target as HTMLInputElement).checked;reset();};
  render();
}
function playerUpdate(next: PlayerState) {
  if (!['present','absent','unknown'].includes(next.captions) || typeof next.videoId!=='string' || !Number.isFinite(next.time) || !Number.isFinite(next.rate)) return;
  const wall=performance.now();
  const old=previousState;
  state=next;
  const changedVideo=next.videoId!==lastVideo;
  if (changedVideo) {force=false;lastVideo=next.videoId;}
  const nextActive=capturing && shouldRecognize(next,force);
  const discontinuous=old && old.videoId===next.videoId && !old.paused && !next.paused && Math.abs(next.time-old.time-(wall-previousWall)/1000*old.rate)>0.9;
  const structural=changedVideo || next.rate!==old?.rate || next.seeking!==old?.seeking || next.ad!==old?.ad || next.captions!==old?.captions || discontinuous;
  if(capturing && structural) reset(changedVideo?'video':next.rate!==old?.rate?'rate':next.seeking!==old?.seeking?'seek':next.ad!==old?.ad?'ad':next.captions!==old?.captions?'captions':'clock');
  else if(capturing && nextActive!==active) {
    active=nextActive;
    void request({type:nextActive?'resume':'pause',state:{generation,active:nextActive,media_time:next.time,rate:next.rate}}).catch(()=>stopLocal('扩展连接已断开'));
  }
  previousState=next; previousWall=wall;
  if (!capturing && !starting) statusText=!paired?'首次使用请打开本机设置页连接扩展':next.captions==='present'?'视频已有字幕，默认使用 YouTube 字幕':next.captions==='absent'?'可开启本地字幕':'正在核对字幕轨道，或无法确定字幕状态';
  if(capturing && !active) statusText=next.ad?'广告期间暂停识别':next.captions==='present'&&!force?'已有字幕，已暂停本地识别':!next.ready||next.paused?'等待视频继续播放':'等待字幕状态确定';
  render();
}
window.addEventListener('message',event=>{
  if(event.source!==window || event.origin!==location.origin || event.data?.source!=='ytls:player' || !event.data.state) return;
  playerUpdate(event.data.state);
});
chrome.runtime.onMessage.addListener((message,_sender,reply)=>{
  if(message.type==='service-event') {
    const event=message.event;
    if(event?.type==='capture-ended') { if(capturing||starting) void stopLocal('音频共享已停止',false); }
    if(event?.type==='status') {
      if(event.generation && event.generation!==generation) return;
      setStatus(labels[event.code] || event.detail || event.code);
      if(event.code==='SESSION_BUSY') void stopLocal(labels.SESSION_BUSY);
    }
    if(event?.generation===generation && event.type==='caption.source' && typeof event.text==='string') {
      caption={id:event.segment_id,generation,en:event.text.slice(0,1500),zh:'',shown:performance.now()};renderCaption();
    }
    if(event?.generation===generation && event.type==='caption.translation' && caption && caption.id===event.segment_id && typeof event.text==='string') {caption.zh=event.text.slice(0,1500);renderCaption();}
    return;
  }
  if(message.type==='prepare-tab-capture') {
    if(capturing) {void stopLocal();reply({ok:true,stop:true});return;}
    if(!eligible()) {shadow?.querySelector<HTMLElement>('#panel')?.removeAttribute('hidden');reply({ok:false});return;}
    generation++;starting=true;reply({ok:true,session:session()});return;
  }
  if(message.type==='tab-capture-started') {starting=false;capturing=true;reset('capture-ready');setStatus('正在等待语音…');}
});
void request({type:'settings'}).then(config=>{paired=!!config.paired;mode=config.mode || 'bilingual';render();}).catch(()=>setStatus('扩展已更新，请刷新页面'));
setInterval(mount,600);
setInterval(renderCaption,1000);
window.addEventListener('pagehide',()=>{void stopLocal('已离开视频页面');});
mount();
