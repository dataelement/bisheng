import { PcmCapture } from "./audio";

export const RECORDING_LIMIT_MS = 600_000;
const BUFFER_LIMIT = 160_000;
const SESSION_TIMEOUT_MS = 20_000;

type Segment = { version: number; text: string; final: boolean };
export class Transcript {
  private segments = new Map<string, Segment>();
  update(event: {
    segment_id: string;
    version: number;
    text: string;
    type: string;
  }): string {
    const old = this.segments.get(event.segment_id);
    if (!old?.final && (!old || event.version > old.version)) {
      this.segments.set(event.segment_id, {
        version: event.version,
        text: event.text,
        final: event.type === "final",
      });
    }
    return [...this.segments.values()].map((segment) => segment.text).join("");
  }
}

export interface VoiceCallbacks {
  onState: (recording: boolean, busy: boolean) => void;
  onText: (text: string) => void;
  onError: (error?: unknown) => void;
  onEnd: () => void;
}
export interface VoiceOptions {
  realtime: boolean;
  modelId: string;
  websocketUrl: string;
  transcribe: (file: FormData) => Promise<string>;
}

/** One recording owns its resources and callbacks, including delayed final text. */
export class VoiceSession {
  private abort = new AbortController();
  private stream: MediaStream | null = null;
  private recorder: MediaRecorder | null = null;
  private capture: PcmCapture | null = null;
  private socket: WebSocket | null = null;
  private buffer: ArrayBuffer[] = [];
  private bufferBytes = 0;
  private ready = false;
  private ended = false;
  private stopping = false;
  private audioEnded = false;
  private finishSent = false;
  private transcript = new Transcript();
  private serverSessionId: string | null = null;
  private limitTimer: ReturnType<typeof setTimeout> | undefined;
  private timeout: ReturnType<typeof setTimeout> | undefined;

  constructor(
    private options: VoiceOptions,
    private callbacks: VoiceCallbacks,
  ) {}

  async start() {
    this.callbacks.onState(true, true);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
      if (this.ended) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }
      this.stream = stream;
      this.limitTimer = setTimeout(() => this.stop(), RECORDING_LIMIT_MS);
      if (this.options.realtime) await this.startRealtime(stream);
      else this.startBatch(stream);
    } catch (error) {
      this.fail(error);
    }
  }

  private startBatch(stream: MediaStream) {
    const mimeType = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"].find(
      (mime) => MediaRecorder.isTypeSupported(mime),
    );
    const recorder = new MediaRecorder(
      stream,
      mimeType ? { mimeType } : undefined,
    );
    this.recorder = recorder;
    const chunks: Blob[] = [];
    recorder.ondataavailable = (event) => {
      if (event.data.size) chunks.push(event.data);
    };
    recorder.onerror = () => this.fail(new Error("Audio recording failed"));
    recorder.onstop = () => {
      if (this.ended) return;
      this.timeout = setTimeout(
        () => this.fail(new Error("Transcription timed out")),
        120_000,
      );
      const form = new FormData();
      form.append(
        "file",
        new Blob(chunks, { type: recorder.mimeType }),
        "recording.webm",
      );
      void this.options
        .transcribe(form)
        .then((text) => {
          if (!this.ended) this.callbacks.onText(text);
          this.complete();
        })
        .catch((error: unknown) => this.fail(error));
    };
    recorder.start();
  }

  private async startRealtime(stream: MediaStream) {
    const socket = new WebSocket(this.options.websocketUrl);
    this.socket = socket;
    this.timeout = setTimeout(
      () => this.fail(new Error("ASR connection timed out")),
      SESSION_TIMEOUT_MS,
    );
    socket.onopen = () => {
      if (!this.ended)
        socket.send(
          JSON.stringify({ type: "start", model_id: this.options.modelId }),
        );
    };
    socket.onmessage = (event) => {
      if (this.ended) return;
      try {
        const message = JSON.parse(String(event.data)) as {
          type: string;
          session_id: string;
          segment_id: string;
          version: number;
          text: string;
        };
        if (message.type === "ready") {
          this.serverSessionId = message.session_id;
          this.ready = true;
          clearTimeout(this.timeout);
          this.flush();
        } else if (message.type === "error") {
          this.fail(new Error("ASR request failed"));
        } else if (message.session_id === this.serverSessionId) {
          if (message.type === "partial" || message.type === "final")
            this.callbacks.onText(this.transcript.update(message));
          else if (message.type === "limit_reached") this.stop();
          else if (message.type === "completed") this.complete();
        }
      } catch (error) {
        this.fail(error);
      }
    };
    socket.onerror = () => this.fail(new Error("ASR connection failed"));
    socket.onclose = () => {
      if (!this.ended) this.fail(new Error("ASR connection closed"));
    };
    this.capture = new PcmCapture(stream, (pcm) => {
      if (this.ended) return;
      this.buffer.push(pcm);
      this.bufferBytes += pcm.byteLength;
      if (
        this.bufferBytes > BUFFER_LIMIT ||
        socket.bufferedAmount > BUFFER_LIMIT
      ) {
        this.fail(new Error("Audio connection is too slow"));
      } else this.flush();
    });
    await this.capture.start(this.abort.signal);
  }

  private flush() {
    if (!this.ready || this.socket?.readyState !== WebSocket.OPEN || this.ended)
      return;
    for (const pcm of this.buffer) this.socket.send(pcm);
    this.buffer = [];
    this.bufferBytes = 0;
    if (this.audioEnded && !this.finishSent) {
      this.finishSent = true;
      this.socket.send(JSON.stringify({ type: "stop" }));
      clearTimeout(this.timeout);
      this.timeout = setTimeout(
        () => this.fail(new Error("ASR finish timed out")),
        SESSION_TIMEOUT_MS,
      );
    }
  }

  stop() {
    if (this.ended || this.stopping) return;
    this.stopping = true;
    clearTimeout(this.limitTimer);
    this.callbacks.onState(false, true);
    if (this.recorder?.state === "recording") {
      this.recorder.stop();
      this.stream?.getTracks().forEach((track) => track.stop());
    } else if (this.capture) {
      void this.capture
        .stop()
        .then(() => {
          this.audioEnded = true;
          this.flush();
        })
        .catch((error: unknown) => this.fail(error));
    } else {
      // A late permission result is released by start() without opening a session.
      this.complete();
    }
  }

  cancel() {
    this.complete();
  }

  private fail(error: unknown) {
    if (this.ended) return;
    console.error("Voice input failed", error);
    this.callbacks.onError(error);
    this.complete();
  }

  private complete() {
    if (this.ended) return;
    this.ended = true;
    this.abort.abort();
    clearTimeout(this.limitTimer);
    clearTimeout(this.timeout);
    this.stream?.getTracks().forEach((track) => track.stop());
    if (this.recorder?.state === "recording") this.recorder.stop();
    this.capture?.close();
    if (this.socket) {
      this.socket.onopen =
        this.socket.onmessage =
        this.socket.onerror =
        this.socket.onclose =
          null;
      this.socket.close();
    }
    this.callbacks.onState(false, false);
    this.callbacks.onEnd();
  }
}
