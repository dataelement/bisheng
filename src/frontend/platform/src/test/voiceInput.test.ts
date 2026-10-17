import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { VoiceDraft } from "../../../shared/voice/draft";
import { PcmPacketizer } from "../../../shared/voice/audio";
import {
  RECORDING_LIMIT_MS,
  Transcript,
  VoiceSession,
} from "../../../shared/voice/session";

const capture = vi.hoisted(() => ({
  stopTrack: vi.fn(),
  emit: (() => {}) as (pcm: ArrayBuffer) => void,
}));
vi.mock("../../../shared/voice/audio", async (original) => ({
  ...(await original<typeof import("../../../shared/voice/audio")>()),
  PcmCapture: class {
    constructor(_stream: MediaStream, emit: (pcm: ArrayBuffer) => void) {
      capture.emit = emit;
    }
    async start() {}
    async stop() {
      capture.stopTrack();
      capture.emit(new ArrayBuffer(2));
    }
    close() {
      capture.stopTrack();
    }
  },
}));

class FakeSocket {
  static OPEN = 1;
  static latest: FakeSocket;
  readyState = 1;
  bufferedAmount = 0;
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  onclose: (() => void) | null = null;
  send = vi.fn();
  close = vi.fn();
  constructor() {
    FakeSocket.latest = this;
  }
  message(event: object) {
    this.onmessage?.({ data: JSON.stringify({ session_id: "s1", ...event }) });
  }
}

class FakeRecorder {
  static isTypeSupported = () => true;
  state = "inactive";
  mimeType = "audio/webm";
  ondataavailable: ((event: { data: Blob }) => void) | null = null;
  onstop: (() => void) | null = null;
  start() {
    this.state = "recording";
  }
  stop() {
    this.state = "inactive";
    queueMicrotask(() => {
      this.ondataavailable?.({ data: new Blob(["audio"]) });
      this.onstop?.();
    });
  }
}

const tick = async () => {
  for (let i = 0; i < 5; i++) await Promise.resolve();
};
const stream = () =>
  ({
    getTracks: () => [{ stop: capture.stopTrack }],
  }) as unknown as MediaStream;
const callbacks = () => ({
  onState: vi.fn(),
  onText: vi.fn(),
  onError: vi.fn(),
  onEnd: vi.fn(),
});

beforeEach(() => {
  vi.clearAllMocks();
  vi.stubGlobal("WebSocket", FakeSocket);
  vi.stubGlobal("MediaRecorder", FakeRecorder);
  Object.defineProperty(navigator, "mediaDevices", {
    configurable: true,
    value: { getUserMedia: vi.fn().mockResolvedValue(stream()) },
  });
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("voice draft ownership", () => {
  it("replaces hypotheses and appends a second recording to the existing text", () => {
    const first = new VoiceDraft("Before ", 7);
    let text = first.apply("Before ", "hel");
    text = first.apply(text, "hello.");
    expect(text).toBe("Before hello.");
    const second = new VoiceDraft(text, text.length);
    expect(second.apply(text, " Next.")).toBe("Before hello. Next.");
  });
  it("preserves edits before and after the dictated span", () => {
    const draft = new VoiceDraft("prefix suffix", 7);
    const text = draft.apply("prefix suffix", "draft");
    expect(draft.apply(`new ${text}!`, "final")).toBe(`new ${text}!`);
    const anchored = new VoiceDraft("prefix suffix", 7);
    const partial = anchored.apply("prefix suffix", "draft");
    expect(anchored.apply(`new ${partial}`, "final")).toBe(
      "new prefix finalsuffix",
    );
    expect(anchored.apply("new prefix finalsuffix!", "done")).toBe(
      "new prefix donesuffix!",
    );
  });
  it("preserves a manual correction inside the dictated span", () => {
    const draft = new VoiceDraft("prefix ", 7);
    draft.apply("prefix ", "wrong");
    expect(draft.reconcile("prefix corrected")).toBe(false);
    expect(draft.apply("prefix corrected", "late result")).toBe(
      "prefix corrected",
    );
  });
  it("keeps old text when an empty recognition finishes", () => {
    expect(new VoiceDraft("old", 3).apply("old", "")).toBe("old");
  });
});

it("deduplicates final events and ignores stale hypotheses", () => {
  const transcript = new Transcript();
  transcript.update({
    type: "partial",
    segment_id: "a",
    version: 2,
    text: "draft",
  });
  expect(
    transcript.update({
      type: "partial",
      segment_id: "a",
      version: 1,
      text: "old",
    }),
  ).toBe("draft");
  transcript.update({
    type: "final",
    segment_id: "a",
    version: 3,
    text: "Done.",
  });
  transcript.update({
    type: "partial",
    segment_id: "a",
    version: 4,
    text: "duplicate",
  });
  expect(
    transcript.update({
      type: "final",
      segment_id: "b",
      version: 1,
      text: " Next.",
    }),
  ).toBe("Done. Next.");
});

it("packetizes 44.1 kHz chunks without discarding boundaries or final samples", () => {
  const pcm = new PcmPacketizer(44100);
  const frames: ArrayBuffer[] = [];
  for (let i = 0; i < 35; i++)
    frames.push(...pcm.push(new Float32Array(128).fill(0.5)));
  frames.push(pcm.flush()!);
  expect(frames.map((frame) => frame.byteLength)).toEqual([3200, 50]);
  expect(new DataView(frames[0]).getInt16(0, true)).toBe(16383);
  expect(pcm.flush()).toBeUndefined();
});

it("pauses immediately, flushes audio before stop, and accepts the late final", async () => {
  const cb = callbacks();
  const session = new VoiceSession(
    {
      realtime: true,
      modelId: "1",
      websocketUrl: "ws://localhost",
      transcribe: vi.fn(),
    },
    cb,
  );
  await session.start();
  const socket = FakeSocket.latest;
  socket.onopen?.();
  socket.message({ type: "ready" });
  socket.message({
    type: "partial",
    segment_id: "a",
    version: 1,
    text: "draft",
  });
  session.stop();
  expect(cb.onState).toHaveBeenLastCalledWith(false, true);
  expect(capture.stopTrack).toHaveBeenCalled();
  await tick();
  const sent = socket.send.mock.calls.map(([data]) => data);
  expect(sent.at(-2)).toBeInstanceOf(ArrayBuffer);
  expect(JSON.parse(sent.at(-1))).toEqual({ type: "stop" });
  socket.message({ type: "final", segment_id: "a", version: 2, text: "final" });
  expect(cb.onText).toHaveBeenLastCalledWith("final");
  expect(cb.onEnd).not.toHaveBeenCalled();
  socket.message({ type: "completed" });
  expect(cb.onState).toHaveBeenLastCalledWith(false, false);
  expect(cb.onEnd).toHaveBeenCalledTimes(1);
  expect(cb.onError).not.toHaveBeenCalled();
});

it("transcribes batch audio only after pause, then permits a fresh session", async () => {
  const cb = callbacks();
  const transcribe = vi.fn().mockResolvedValue("batch");
  const options = {
    realtime: false,
    modelId: "1",
    websocketUrl: "",
    transcribe,
  };
  const first = new VoiceSession(options, cb);
  await first.start();
  expect(transcribe).not.toHaveBeenCalled();
  first.stop();
  expect(cb.onState).toHaveBeenLastCalledWith(false, true);
  await tick();
  expect(cb.onText).toHaveBeenLastCalledWith("batch");
  const second = new VoiceSession(options, cb);
  await second.start();
  second.stop();
  await tick();
  expect(transcribe).toHaveBeenCalledTimes(2);
  expect(cb.onEnd).toHaveBeenCalledTimes(2);
});

it("releases a late permission result after the user already paused", async () => {
  let grant: (value: MediaStream) => void = () => {};
  vi.mocked(navigator.mediaDevices.getUserMedia).mockReturnValue(
    new Promise((resolve) => {
      grant = resolve;
    }),
  );
  const cb = callbacks();
  const session = new VoiceSession(
    { realtime: true, modelId: "1", websocketUrl: "", transcribe: vi.fn() },
    cb,
  );
  const started = session.start();
  session.stop();
  grant(stream());
  await started;
  expect(capture.stopTrack).toHaveBeenCalled();
  expect(cb.onEnd).toHaveBeenCalledTimes(1);
  expect(cb.onText).not.toHaveBeenCalled();
});

it("preserves the existing ten-minute automatic pause", async () => {
  vi.useFakeTimers();
  const cb = callbacks();
  const session = new VoiceSession(
    {
      realtime: false,
      modelId: "1",
      websocketUrl: "",
      transcribe: vi.fn().mockResolvedValue(""),
    },
    cb,
  );
  await session.start();
  await vi.advanceTimersByTimeAsync(RECORDING_LIMIT_MS);
  expect(cb.onState).toHaveBeenCalledWith(false, true);
  expect(cb.onEnd).toHaveBeenCalledOnce();
  expect(cb.onError).not.toHaveBeenCalled();
});
