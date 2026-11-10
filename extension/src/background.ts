let creating: Promise<void> | null = null;
async function offscreen() {
  const existing = await chrome.runtime.getContexts({contextTypes: [chrome.runtime.ContextType.OFFSCREEN_DOCUMENT]});
  if (existing.length) return;
  if (!creating) creating = chrome.offscreen.createDocument({url: 'offscreen.html', reasons: [chrome.offscreen.Reason.USER_MEDIA], justification: 'Capture the explicitly selected tab and connect to the local subtitle service.'}).finally(() => { creating = null; });
  await creating;
}
async function toOffscreen(message: any) {
  await offscreen();
  return chrome.runtime.sendMessage({...message, target: 'offscreen'});
}
async function settings() {
  return chrome.storage.local.get({token: '', port: 18765, mode: 'bilingual'});
}
function isYouTube(url = '') { try { return new URL(url).origin === 'https://www.youtube.com'; } catch { return false; } }
chrome.runtime.onMessage.addListener((message, sender, reply) => {
  if (message?.target !== 'background') return;
  const run = async () => {
    if (message.type === 'to-content' && sender.url === chrome.runtime.getURL('offscreen.html')) {
      if (typeof message.tabId === 'number') await chrome.tabs.sendMessage(message.tabId, {type: 'service-event', event: message.event}).catch(() => undefined);
      return {ok: true};
    }
    if (!sender.tab || !isYouTube(sender.url)) throw new Error('Invalid sender');
    const tabId = sender.tab.id!;
    if (message.type === 'settings') {
      const value = await settings();
      return {ok: true, paired: !!value.token, port: value.port, mode: value.mode};
    }
    if (message.type === 'mode') {
      if (!['english','chinese','bilingual'].includes(message.mode)) throw new Error('Invalid mode');
      await chrome.storage.local.set({mode: message.mode});
      const existing=await chrome.runtime.getContexts({contextTypes:[chrome.runtime.ContextType.OFFSCREEN_DOCUMENT]});
      if(existing.length) await toOffscreen({type: 'mode', tabId, mode: message.mode});
      return {ok:true};
    }
    if (message.type === 'connect') {
      const config = await settings();
      if (!config.token) throw new Error('请先打开本机设置页连接扩展');
      return toOffscreen({type: 'connect', tabId, config, session: message.session});
    }
    if (['audio','reset','stop','pause','resume'].includes(message.type)) {
      if (message.type === 'audio' && (!Array.isArray(message.data) || message.data.length > 3200)) throw new Error('Invalid audio');
      return toOffscreen({...message, tabId});
    }
    throw new Error('Unknown request');
  };
  void run().then(reply).catch(error => reply({ok: false, error: error.message}));
  return true;
});
chrome.runtime.onMessageExternal.addListener((message, sender, reply) => {
  let source: URL;
  try { source = new URL(sender.url || ''); } catch { return; }
  if (source.protocol !== 'http:' || source.hostname !== '127.0.0.1' || source.pathname !== '/setup' || source.port !== String(message?.port)) return;
  if (message?.type !== 'pair' || !/^[A-Za-z0-9_-]{32,100}$/.test(message.token || '') || !Number.isInteger(message.port) || message.port < 1024 || message.port > 65535) return;
  void chrome.storage.local.set({token: message.token, port: message.port}).then(() => reply({ok: true}));
  return true;
});
async function toggle(tab: chrome.tabs.Tab) {
  if (!tab.id || !isYouTube(tab.url)) return;
  try {
    const preparation = await chrome.tabs.sendMessage(tab.id, {type: 'prepare-tab-capture'});
    if (!preparation?.ok) return;
    if (preparation.stop) { await toOffscreen({type: 'stop', tabId: tab.id}); return; }
    const streamId = await chrome.tabCapture.getMediaStreamId({targetTabId: tab.id});
    const config = await settings();
    if (!config.token) throw new Error('请先打开本机设置页连接扩展');
    const result = await toOffscreen({type: 'connect', tabId: tab.id, config, session: preparation.session, streamId});
    if (!result?.ok) throw new Error(result?.error || '启动失败');
    await chrome.tabs.sendMessage(tab.id, {type: 'tab-capture-started'});
  } catch (error) { await chrome.tabs.sendMessage(tab.id, {type: 'service-event', event: {type: 'status', code: 'CAPTURE_FAILED', detail: String(error)}}).catch(() => undefined); }
}
chrome.action.onClicked.addListener(tab => { void toggle(tab); });
chrome.commands.onCommand.addListener(command => {
  if (command === 'toggle-capture') void chrome.tabs.query({active: true, currentWindow: true}).then(tabs => tabs[0] && toggle(tabs[0]));
});
chrome.tabs.onRemoved.addListener(tabId => { void toOffscreen({type: 'stop', tabId}).catch(() => undefined); });
