import { captionControlUnavailable, captionsFromResponse } from './common';

const handle = 'ytls:' + crypto.randomUUID();
let configured = false;
let candidate = ''; let candidateSince = 0;
function poll() {
  if (!configured && navigator.mediaDevices && 'setCaptureHandleConfig' in navigator.mediaDevices) {
    try {
      (navigator.mediaDevices as any).setCaptureHandleConfig({handle, exposeOrigin: true, permittedOrigins: [location.origin]});
      configured = true;
    } catch { /* Capability checked again by the capturing side. */ }
  }
  const videoId = new URL(location.href).searchParams.get('v') || '';
  const video = document.querySelector<HTMLVideoElement>('video.html5-main-video');
  const player = document.getElementById('movie_player') as any;
  if (!video || !player || !videoId) return;
  let response: any; let tracks: unknown;
  try { response = player.getPlayerResponse?.() || (window as any).ytInitialPlayerResponse; tracks = player.getOption?.('captions', 'tracklist'); } catch { /* Unknown is safe. */ }
  const button = player.querySelector('.ytp-subtitles-button') as HTMLElement | null;
  let cc: boolean | null = null;
  let unavailable = false;
  if (button) {
    const style = getComputedStyle(button);
    unavailable = captionControlUnavailable(button.getAttribute('aria-label') || '', button.getAttribute('aria-disabled') === 'true' || button.hasAttribute('disabled'));
    cc = !(unavailable || style.display === 'none');
  }
  let captions = captionsFromResponse(response, videoId, cc, tracks, unavailable);
  const next = videoId + ':' + captions;
  if (next !== candidate) { candidate = next; candidateSince = performance.now(); }
  if (captions === 'absent' && performance.now() - candidateSince < 1800) captions = 'unknown';
  window.postMessage({source: 'ytls:player', state: {
    videoId, captions, paused: video.paused, ended: video.ended, seeking: video.seeking,
    ready: video.readyState >= 3, ad: player.classList.contains('ad-showing') || player.classList.contains('ad-interrupting'),
    time: video.currentTime, rate: video.playbackRate, handle,
  }}, location.origin);
}
setInterval(poll, 400);
document.addEventListener('yt-navigate-finish', poll);
