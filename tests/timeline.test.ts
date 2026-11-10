import {describe,expect,it} from 'vitest';
import {CaptionTimeline} from '../extension/src/timeline';
const source=(id:number,start:number,end:number,text='source')=>({type:'caption.source',segment_id:id,media_start:start,media_end:end,text});
describe('media-clock subtitle scheduling',()=>{
  it('never displays a future cue just because inference has completed',()=>{
    const timeline=new CaptionTimeline();timeline.put(source(1,10,14));
    expect(timeline.at(9.99)).toBeNull();expect(timeline.at(10)?.en).toBe('source');
  });
  it('expires on the video clock, including when an old translation arrives late',()=>{
    const timeline=new CaptionTimeline();timeline.put(source(1,10,14));
    timeline.put({...source(1,10,14,'旧译文'),type:'caption.translation'});
    expect(timeline.at(14)).toBeNull();expect(timeline.at(20)).toBeNull();
  });
  it('can replay cached bilingual cues after a backward seek',()=>{
    const timeline=new CaptionTimeline();timeline.put(source(1,10,14));
    timeline.put({...source(1,10,14,'中文'),type:'caption.translation'});
    expect(timeline.at(25)).toBeNull();expect(timeline.at(12)?.zh).toBe('中文');
  });
  it('selects using the media position rather than elapsed wall time or playback rate',()=>{
    const timeline=new CaptionTimeline();timeline.put(source(1,0,4));timeline.put(source(2,4,8,'next'));
    expect(timeline.at(3.9)?.id).toBe(1);expect(timeline.at(4)?.id).toBe(2);
    expect(timeline.at(4)?.id).toBe(2); // Pausing preserves the same subtitle.
  });
  it('bounds memory and rejects invalid cue timestamps',()=>{
    const timeline=new CaptionTimeline(2);timeline.put(source(1,0,4));timeline.put(source(2,4,8));timeline.put(source(3,8,12));
    timeline.put(source(4,NaN,20));timeline.put(source(5,20,19));
    expect(timeline.size).toBe(2);expect(timeline.at(1)).toBeNull();
  });
});
