/** Stateful resampling keeps chunk boundaries from dropping audio samples. */
export class PcmPacketizer {
  private pending: number[] = [];
  constructor(private readonly sampleRate: number) {}

  push(samples: Float32Array): ArrayBuffer[] {
    this.pending.push(...samples);
    const frames: ArrayBuffer[] = [];
    const sourceFrameSize = Math.round(this.sampleRate / 10);
    while (this.pending.length >= sourceFrameSize) {
      frames.push(this.encode(this.pending.splice(0, sourceFrameSize)));
    }
    return frames;
  }

  flush(): ArrayBuffer | undefined {
    if (!this.pending.length) return undefined;
    return this.encode(this.pending.splice(0));
  }

  private encode(samples: number[]): ArrayBuffer {
    const length = Math.round((samples.length * 16000) / this.sampleRate);
    const buffer = new ArrayBuffer(length * 2);
    const data = new DataView(buffer);
    for (let i = 0; i < length; i++) {
      const from = Math.floor((i * samples.length) / length);
      const to = Math.max(
        from + 1,
        Math.floor(((i + 1) * samples.length) / length),
      );
      let sum = 0;
      for (let j = from; j < to; j++) sum += samples[j];
      const sample = Math.max(-1, Math.min(1, sum / (to - from)));
      data.setInt16(i * 2, sample < 0 ? sample * 32768 : sample * 32767, true);
    }
    return buffer;
  }
}

const workletSource = `
class Capture extends AudioWorkletProcessor {
  constructor() {
    super();
    this.port.onmessage = () => this.port.postMessage({ flushed: true });
  }
  process(inputs) {
    const samples = inputs[0] && inputs[0][0];
    if (samples) this.port.postMessage(samples.slice());
    return true;
  }
}
registerProcessor('bisheng-asr-capture', Capture);
`;

export class PcmCapture {
  private context: AudioContext;
  private source: MediaStreamAudioSourceNode;
  private node: AudioWorkletNode | null = null;
  private mute: GainNode;
  private packetizer: PcmPacketizer;
  private flushCallback: (() => void) | null = null;
  private closing: Promise<void> | null = null;
  private closed = false;

  constructor(
    private stream: MediaStream,
    private emit: (pcm: ArrayBuffer) => void,
  ) {
    this.context = new AudioContext({ sampleRate: 16000 });
    this.packetizer = new PcmPacketizer(this.context.sampleRate);
    this.source = this.context.createMediaStreamSource(stream);
    this.mute = this.context.createGain();
    this.mute.gain.value = 0;
  }

  async start(signal: AbortSignal) {
    const url = URL.createObjectURL(
      new Blob([workletSource], { type: "application/javascript" }),
    );
    try {
      await this.context.audioWorklet.addModule(url);
      if (signal.aborted || this.closed) return;
      this.node = new AudioWorkletNode(this.context, "bisheng-asr-capture");
      this.node.port.onmessage = (
        event: MessageEvent<Float32Array | { flushed: true }>,
      ) => {
        if (this.closed) return;
        if ("flushed" in event.data) this.flushCallback?.();
        else
          for (const frame of this.packetizer.push(event.data))
            this.emit(frame);
      };
      this.source.connect(this.node);
      this.node.connect(this.mute);
      this.mute.connect(this.context.destination);
      await this.context.resume();
    } finally {
      URL.revokeObjectURL(url);
    }
  }

  stop(): Promise<void> {
    this.stream.getTracks().forEach((track) => track.stop());
    if (this.closing) return this.closing;
    this.closing = (async () => {
      if (this.node && !this.closed) {
        await new Promise<void>((resolve) => {
          const timer = setTimeout(resolve, 300);
          this.flushCallback = () => {
            clearTimeout(timer);
            resolve();
          };
          this.node?.port.postMessage("flush");
        });
      }
      const remaining = this.packetizer.flush();
      if (remaining && !this.closed) this.emit(remaining);
      this.close();
    })();
    return this.closing;
  }

  close() {
    if (this.closed) return;
    this.closed = true;
    this.stream.getTracks().forEach((track) => track.stop());
    this.source.disconnect();
    this.node?.disconnect();
    this.mute.disconnect();
    if (this.context.state !== "closed")
      void this.context.close().catch(console.error);
  }
}
