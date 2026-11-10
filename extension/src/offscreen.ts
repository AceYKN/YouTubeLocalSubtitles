import {makeAudioGraph, packAudio} from './common';

let socket: WebSocket | null = null;
let activeTab: number | null = null;
let current: any = null;
let stream: MediaStream | null = null;
let graph: Awaited<ReturnType<typeof makeAudioGraph>> | null = null;
let playback: AudioContext | null = null;
let sequence = 0;
let mediaAnchor = 0;
let anchorTime = 0;
const controls: any[]=[];

async function event(message: any, tab = activeTab) {
  if (tab !== null) await chrome.runtime.sendMessage({target: 'background', type: 'to-content', tabId: tab, event: message}).catch(() => undefined);
}
async function stop() {
  const previous = activeTab; activeTab = null;
  if (socket) { socket.onclose = null; socket.close(); socket = null; }
  if (graph) { await graph.close(); graph = null; }
  stream?.getTracks().forEach(track => track.stop()); stream = null;
  if (playback) { await playback.close(); playback = null; }
  current = null;
  await event({type: 'capture-ended'}, previous);
}
function audio(message: any) {
  if (!current?.active || socket?.readyState !== WebSocket.OPEN || message.generation !== current.generation) return;
  if (socket.bufferedAmount > 262144) { void event({type: 'status', code: 'QUEUE_OVERFLOW'}); return; }
  socket.send(packAudio(message.data, message.generation, message.sequence, message.media_start, message.rate));
}
async function connect(message: any) {
  await stop(); activeTab = message.tabId; current = message.session;
  const ws = new WebSocket(`ws://127.0.0.1:${message.config.port}/v1/session`); socket = ws;
  await new Promise<void>((resolve, reject) => {
    const timer = setTimeout(() => { ws.close(); reject(new Error('本机服务连接超时，请运行 Start.cmd')); }, 8000);
    ws.onopen = () => ws.send(JSON.stringify({type: 'hello', token: message.config.token}));
    ws.onerror = () => { clearTimeout(timer); reject(new Error('无法连接本机服务，请运行 Start.cmd')); };
    ws.onclose = () => { clearTimeout(timer); reject(new Error('本机服务拒绝连接，请重新配对')); };
    ws.onmessage = ({data}) => {
      const value = JSON.parse(data);
      if (value.type === 'hello') { clearTimeout(timer); ws.send(JSON.stringify({type:'session.start', ...current})); resolve(); }
      else void event(value);
    };
  });
  ws.onclose = () => { void event({type:'status',code:'SERVICE_DISCONNECTED'}); void stop(); };
  if (message.streamId) {
    stream = await navigator.mediaDevices.getUserMedia({audio: {mandatory: {chromeMediaSource:'tab',chromeMediaSourceId:message.streamId}} as any, video:false});
    stream.getTracks().forEach(track => track.addEventListener('ended', () => { void stop(); }));
    playback = new AudioContext(); playback.createMediaStreamSource(stream).connect(playback.destination); await playback.resume();
    sequence = 0; mediaAnchor = current.media_time || 0; anchorTime = performance.now();
    graph = await makeAudioGraph(stream, data => audio({data,generation:current.generation,sequence:sequence++,media_start:mediaAnchor + (performance.now()-anchorTime)/1000*current.rate-0.1*current.rate,rate:current.rate}));
  }
  return {ok:true};
}
chrome.runtime.onMessage.addListener((message, _sender, reply) => {
  if (message?.target !== 'offscreen') return;
  const run = async () => {
    if(message.type==='diagnostics')return {ok:true,current,controls};
    if(message.type!=='audio'){controls.push({type:message.type,generation:message.state?.generation});if(controls.length>20)controls.shift();}
    if (message.type === 'connect') return connect(message);
    if (message.tabId !== activeTab) return {ok:false,error:'会话已停止'};
    if (message.type === 'stop') await stop();
    if (message.type === 'mode' && socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify({type:'session.mode',mode:message.mode}));
    if (message.type === 'reset') {
      current = {...current,...message.state}; sequence=0; mediaAnchor=current.media_time || 0; anchorTime=performance.now();
      if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify({type:'session.reset',...message.state}));
    }
    if (message.type === 'pause' || message.type === 'resume') {
      current={...current,...message.state};mediaAnchor=current.media_time || 0;anchorTime=performance.now();
      if(socket?.readyState===WebSocket.OPEN) socket.send(JSON.stringify({type:`session.${message.type}`,generation:current.generation}));
    }
    if (message.type === 'audio') audio(message);
    return {ok:true};
  };
  void run().then(reply).catch(async error => { await stop(); reply({ok:false,error:error.message}); });
  return true;
});
