export type Mode = 'english' | 'chinese' | 'bilingual';
export type CaptionState = 'present' | 'absent' | 'unknown';
export interface PlayerState {
  videoId: string; captions: CaptionState; paused: boolean; ended: boolean;
  seeking: boolean; ready: boolean; ad: boolean; time: number; rate: number; handle: string;
}
export interface CaptureHandle { handle?: string; origin?: string }
export interface HandleTrack extends MediaStreamTrack { getCaptureHandle?: () => CaptureHandle | null }

export function captionControlUnavailable(label: string, disabled: boolean): boolean {
  return disabled || /unavailable|not available|不可用|无法使用|無法使用|无法提供|無法提供|没有字幕|沒有字幕|不提供字幕/i.test(label.normalize('NFKC'));
}

export function captionsFromResponse(response: any, videoId: string, cc: boolean | null, tracks?: unknown, unavailable = false): CaptionState {
  if (!videoId || response?.videoDetails?.videoId !== videoId || response?.playabilityStatus?.status !== 'OK') return 'unknown';
  const list = response?.captions?.playerCaptionsTracklistRenderer?.captionTracks;
  // Advertised ASR tracks can be placeholders with an empty timedtext response.
  // Explicit native unavailability is distinct from CC being toggled off or hidden.
  if (unavailable) {
    if (Array.isArray(tracks) && tracks.length > 0) return 'unknown';
    return response?.streamingData ? 'absent' : 'unknown';
  }
  if (Array.isArray(list) && list.length > 0) return 'present';
  if (Array.isArray(list) && list.length === 0) return 'absent';
  if (cc === false && ((Array.isArray(tracks) && tracks.length === 0) || response?.streamingData)) return 'absent';
  // getOption('captions', 'tracklist') can retain another video's tracks during
  // SPA navigation. Its contents alone cannot establish current availability.
  return 'unknown';
}

export function shouldRecognize(state: PlayerState | null, force: boolean): boolean {
  return !!state && !!state.videoId && !state.paused && !state.ended && !state.seeking && state.ready && !state.ad && (state.captions === 'absent' || force);
}

export function packAudio(data: number[], generation: number, sequence: number, media: number, rate: number): ArrayBuffer {
  if (!data.length || data.length > 3200 || !Number.isFinite(media) || !Number.isFinite(rate)) throw new Error('Invalid audio');
  const buffer = new ArrayBuffer(32 + data.length * 2);
  const view = new DataView(buffer);
  ['Y', 'T', 'L', 'S'].forEach((v, i) => view.setUint8(i, v.charCodeAt(0)));
  view.setUint32(4, generation, true); view.setUint32(8, sequence, true);
  view.setFloat64(12, Math.max(0, media), true); view.setFloat32(20, rate, true);
  view.setUint32(24, data.length, true);
  data.forEach((v, i) => view.setInt16(32 + i * 2, Math.max(-32768, Math.min(32767, v)), true));
  return buffer;
}

export async function makeAudioGraph(stream: MediaStream, onAudio: (data: number[]) => void) {
  // Chrome performs stateful band-limited resampling at the AudioContext boundary.
  const context = new AudioContext({ sampleRate: 16000 });
  try {
    if (context.sampleRate !== 16000) throw new Error('当前浏览器不支持 16kHz 音频处理');
    await context.audioWorklet.addModule(chrome.runtime.getURL('capture-worklet.js'));
    const source = context.createMediaStreamSource(stream);
    const processor = new AudioWorkletNode(context, 'ytls-pcm');
    const silent = context.createGain(); silent.gain.value = 0;
    processor.port.onmessage = event => onAudio(Array.from(new Int16Array(event.data)));
    source.connect(processor).connect(silent).connect(context.destination);
    await context.resume();
    return { close: async () => { processor.port.onmessage = null; source.disconnect(); processor.disconnect(); silent.disconnect(); await context.close(); } };
  } catch (error) { await context.close(); throw error; }
}
