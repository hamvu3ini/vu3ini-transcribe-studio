// Downsamples microphone audio to 16 kHz mono Int16 and posts ~100 ms chunks.
class PcmWorklet extends AudioWorkletProcessor {
  constructor() { super(); this.ratio = sampleRate / 16000; this.acc = []; this.pos = 0; }
  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (!ch) return true;
    let peak = 0;
    for (let i = 0; i < ch.length; i++) peak = Math.max(peak, Math.abs(ch[i]));
    // simple decimation with averaging
    while (this.pos < ch.length) {
      const a = Math.floor(this.pos), b = Math.min(ch.length, Math.floor(this.pos + this.ratio));
      let s = 0, n = 0;
      for (let k = a; k < Math.max(b, a + 1); k++) { s += ch[k]; n++; }
      this.acc.push(s / n);
      this.pos += this.ratio;
    }
    this.pos -= ch.length;
    if (this.acc.length >= 1600) {
      const out = new Int16Array(this.acc.length);
      for (let i = 0; i < this.acc.length; i++) out[i] = Math.max(-32768, Math.min(32767, Math.round(this.acc[i] * 32767)));
      this.port.postMessage({ pcm: out.buffer, peak }, [out.buffer]);
      this.acc = [];
    }
    return true;
  }
}
registerProcessor("pcm-worklet", PcmWorklet);
