void chrome.storage.local.get({token:'',port:18765}).then(config => {
  document.getElementById('status')!.textContent = config.token ? '扩展已配对。请确认本机服务已启动。' : '扩展尚未配对。';
  document.getElementById('setup')!.onclick = () => { window.open(`http://127.0.0.1:${config.port}/setup`); };
});
