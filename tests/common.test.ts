import {describe,expect,it} from 'vitest';
import {captionControlUnavailable,captionsFromResponse,packAudio,shouldRecognize,type PlayerState} from '../extension/src/common';

const response = {videoDetails:{videoId:'abc'},playabilityStatus:{status:'OK'},streamingData:{formats:[]}};
const playing:PlayerState={videoId:'abc',captions:'absent',paused:false,ended:false,seeking:false,ready:true,ad:false,time:20,rate:1,handle:'test'};
describe('caption availability and inference gate',()=>{
  it('does not confuse an off or hidden CC display with unavailable captions',()=>{
    expect(captionsFromResponse({...response,captions:{playerCaptionsTracklistRenderer:{captionTracks:[{kind:'asr'}]}}},'abc',false)).toBe('present');
  });
  it('rejects the advertised but unavailable automatic track from the BBC regression',()=>{
    const bbc={...response,captions:{playerCaptionsTracklistRenderer:{captionTracks:[{kind:'asr',languageCode:'en'}]}}};
    expect(captionsFromResponse(bbc,'abc',false,[],true)).toBe('absent');
    expect(captionsFromResponse(bbc,'abc',true,[],false)).toBe('present');
  });
  it('does not let an old player-module track override an explicitly empty current response',()=>{
    expect(captionsFromResponse({...response,captions:{playerCaptionsTracklistRenderer:{captionTracks:[]}}},'abc',true,[{languageCode:'en'}])).toBe('absent');
    expect(captionsFromResponse(response,'abc',true,[{languageCode:'en'}])).toBe('unknown');
  });
  it('keeps conflicting native availability unknown until the player settles',()=>{
    expect(captionsFromResponse(response,'abc',false,[{languageCode:'en'}],true)).toBe('unknown');
  });
  it.each(['Subtitles/closed captions unavailable','字幕无法使用','字幕無法使用','沒有字幕','Subtitles not available'])('recognizes explicit native unavailability: %s',label=>{
    expect(captionControlUnavailable(label,false)).toBe(true);
  });
  it('does not treat an off CC toggle as unavailable',()=>{
    expect(captionControlUnavailable('Subtitles/closed captions (c)',false)).toBe(false);
    expect(captionControlUnavailable('字幕 (c)',false)).toBe(false);
    expect(captionControlUnavailable('字幕 (c)',true)).toBe(true);
  });
  it('does not use metadata left over from the previous video',()=>expect(captionsFromResponse(response,'next',false,[])).toBe('unknown'));
  it('requires evidence beyond an omitted captions field',()=>{
    expect(captionsFromResponse(response,'abc',null)).toBe('unknown');
    expect(captionsFromResponse(response,'abc',false)).toBe('absent');
    expect(captionsFromResponse(response,'abc',true)).toBe('unknown');
  });
  it.each(['ad','paused','ended','seeking'] as const)('blocks audio while %s, including forced mode',flag=>expect(shouldRecognize({...playing,[flag]:true},true)).toBe(false));
  it('unknown and present captions require manual force',()=>{
    expect(shouldRecognize({...playing,captions:'unknown'},false)).toBe(false);
    expect(shouldRecognize({...playing,captions:'present'},false)).toBe(false);
    expect(shouldRecognize({...playing,captions:'present'},true)).toBe(true);
  });
});
describe('binary media timing contract',()=>{
  it('preserves media time and playback rate independently of audio sample count',()=>{
    const buffer=packAudio([-32768,32767],3,7,40.5,1.5),view=new DataView(buffer);
    expect(buffer.byteLength).toBe(36);
    expect(view.getUint32(4,true)).toBe(3);expect(view.getUint32(8,true)).toBe(7);
    expect(view.getFloat64(12,true)).toBe(40.5);expect(view.getFloat32(20,true)).toBe(1.5);
    expect(view.getUint32(24,true)).toBe(2);expect(view.getInt16(32,true)).toBe(-32768);
  });
  it('refuses unbounded or non-finite frames',()=>{
    expect(()=>packAudio(Array(3201).fill(0),1,0,0,1)).toThrow();
    expect(()=>packAudio([0],1,0,NaN,1)).toThrow();
  });
});
