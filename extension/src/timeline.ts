export interface CueEvent {
  type: string; segment_id: number; media_start: number; media_end: number; text: string;
}
export interface Cue { id: number; start: number; end: number; en: string; zh: string }

export class CaptionTimeline {
  private cues: Cue[] = [];
  constructor(private limit = 256) {}
  clear() { this.cues = []; }
  put(event: CueEvent) {
    if (!Number.isFinite(event.media_start) || !Number.isFinite(event.media_end) || event.media_start < 0 || event.media_end <= event.media_start || event.media_end - event.media_start > 30 || typeof event.text !== 'string') return;
    let cue=this.cues.find(c=>c.id===event.segment_id);
    if (!cue) {
      cue={id:event.segment_id,start:event.media_start,end:event.media_end,en:'',zh:''};
      this.cues.push(cue);
      this.cues.sort((a,b)=>a.start-b.start);
      if(this.cues.length>this.limit)this.cues.splice(0,this.cues.length-this.limit);
    }
    if(event.type==='caption.source')cue.en=event.text.slice(0,1500);
    if(event.type==='caption.translation')cue.zh=event.text.slice(0,1500);
  }
  at(time: number, lateTolerance = 0): Cue | null {
    // A late result must never flash over an unrelated later scene.
    for(let i=this.cues.length-1;i>=0;i--) {
      const cue=this.cues[i];
      if(cue.start<=time && time<cue.end+lateTolerance && cue.en)return cue;
    }
    return null;
  }
  get size() {return this.cues.length;}
}
