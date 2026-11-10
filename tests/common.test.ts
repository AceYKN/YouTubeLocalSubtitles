import {describe,expect,it} from 'vitest';
import {captionsFromResponse,packAudio,shouldRecognize,type PlayerState} from '../extension/src/common';

const response = {videoDetails:{videoId:'abc'},playabilityStatus:{status:'OK'},streamingData:{formats:[]}};
const playing:PlayerState={videoId:'abc',captions:'absent',paused:false,ended:false,seeking:false,ready:true,ad:false,time:20,rate:1,handle:'test'};
describe('caption availability and inference gate',()=>{
  it('does not confuse a disabled CC display with an existing caption track',()=>{
    expect(captionsFromResponse({...response,captions:{playerCaptionsTracklistRenderer:{captionTracks:[{kind:'asr'}]}}},'abc',false)).toBe('present');
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
