declare const AudioWorkletProcessor: { new(): {port: MessagePort} };
declare function registerProcessor(name: string, processor: any): void;

class PCMProcessor extends AudioWorkletProcessor {
  private buffer = new Int16Array(1600);
  private offset = 0;
  process(inputs: Float32Array[][]) {
    const channels = inputs[0];
    if (!channels?.length) return true;
    for (let i = 0; i < channels[0].length; i++) {
      let value = 0;
      for (const channel of channels) value += channel[i] || 0;
      value = Math.max(-1, Math.min(1, value / channels.length));
      this.buffer[this.offset++] = Math.round(value * (value < 0 ? 32768 : 32767));
      if (this.offset === 1600) {
        this.port.postMessage(this.buffer.buffer, [this.buffer.buffer]);
        this.buffer = new Int16Array(1600); this.offset = 0;
      }
    }
    return true;
  }
}
registerProcessor('ytls-pcm', PCMProcessor);
