/**
 * What a support engineer needs from a crash, and the three shapes it gets
 * handed over in: on screen, in a QR code, and in a downloaded file.
 *
 * The point of collecting this in one place is that all three have to agree.
 * A user sends a screenshot; an engineer reads the QR out of it; the two have
 * to name the same incident, or the round trip is wasted. Both apps build the
 * payloads from here for the same reason.
 */

/** Everything gathered about one crash. */
export interface ErrorDiagnostics {
  /** This occurrence. Ties the screenshot, the QR and the downloaded file together. */
  traceId: string;
  /** This *bug*, not this occurrence — the same fault always yields the same code. */
  errorCode: string;
  /** ISO 8601, UTC. */
  timestamp: string;
  /** Build the app is running, as the host supplies it (e.g. `v2.6.0+20260806-1432`). */
  version: string;
  /** Route the crash happened on, path and query only — no origin. */
  route: string;
  /** Who hit it, when the host knows. */
  user?: string;
  message: string;
  /** First stack frame that belongs to the app, for the compact payloads. */
  topFrame?: string;
  stack?: string;
  browser: {
    userAgent: string;
    language: string;
    viewport: string;
    /** Device pixel ratio and page zoom both change what the user actually saw. */
    devicePixelRatio: number;
  };
}

export interface CollectDiagnosticsInput {
  error: { message?: string; stack?: string; status?: number; statusText?: string };
  /** Host-supplied build string; hosts that cannot produce one pass "unknown". */
  version: string;
  user?: string;
  /** Overridable so tests are not at the mercy of the clock. */
  now?: Date;
}

/**
 * Alphabet without I, L, O and U: the codes get read down a phone line and
 * typed into a ticket, and those four are the ones that come back wrong.
 */
const CODE_ALPHABET = '0123456789ABCDEFGHJKMNPQRSTVWXYZ';

/** FNV-1a, seeded — two passes give the 40 bits the code needs. */
function fnv1a(input: string, seed: number): number {
  let hash = seed;
  for (let i = 0; i < input.length; i += 1) {
    hash ^= input.charCodeAt(i);
    hash = Math.imul(hash, 0x01000193) >>> 0;
  }
  return hash >>> 0;
}

function toCode(value: number, length: number): string {
  let out = '';
  let rest = value;
  for (let i = 0; i < length; i += 1) {
    out = CODE_ALPHABET[rest % CODE_ALPHABET.length] + out;
    rest = Math.floor(rest / CODE_ALPHABET.length);
  }
  return out;
}

/**
 * A short, stable name for the fault itself.
 *
 * Derived from the message and the frame it was thrown in, so two users hitting
 * the same bug quote the same code and the reports can be piled together —
 * which is what the occurrence id deliberately cannot do.
 */
export function deriveErrorCode(message: string, topFrame?: string): string {
  const signature = `${message}\n${topFrame ?? ''}`;
  return `${toCode(fnv1a(signature, 0x811c9dc5), 4)}-${toCode(fnv1a(signature, 0x9e3779b9), 4)}`;
}

/** Random enough to be unique per crash; not a secret, and not a session id. */
function newTraceId(): string {
  const bytes = new Uint8Array(8);
  if (typeof crypto !== 'undefined' && typeof crypto.getRandomValues === 'function') {
    crypto.getRandomValues(bytes);
  } else {
    for (let i = 0; i < bytes.length; i += 1) {
      bytes[i] = Math.floor(Math.random() * 256);
    }
  }
  return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
}

/**
 * First frame that looks like application code.
 *
 * Frames inside the framework runtime are the same for every crash and say
 * nothing about which one this is, so they are skipped in favour of the first
 * frame that names a source file.
 */
export function pickTopFrame(stack?: string): string | undefined {
  if (!stack) {
    return undefined;
  }
  const frames = stack
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line.startsWith('at ') || line.includes('@'));
  const appFrame = frames.find((line) => !/node_modules|\/vendor[-.]|chunk-[A-Z0-9]+\.js/.test(line));
  // Drop the origin. It is the same for every frame of every crash, and in the
  // QR payload it costs the characters that the file and line number need — the
  // one part of the frame that says which crash this is.
  return appFrame == null && frames[0] == null
    ? undefined
    : (appFrame ?? frames[0]).replace(/https?:\/\/[^/]+\//g, '').slice(0, 120);
}

export function collectDiagnostics({ error, version, user, now }: CollectDiagnosticsInput): ErrorDiagnostics {
  const at = now ?? new Date();
  const statusPrefix =
    typeof error.status === 'number' ? `${error.status} ${error.statusText ?? ''}`.trim() : '';
  const message = [statusPrefix, error.message].filter(Boolean).join(' — ') || 'Unknown error';
  const topFrame = pickTopFrame(error.stack);

  return {
    traceId: newTraceId(),
    errorCode: deriveErrorCode(message, topFrame),
    timestamp: at.toISOString(),
    version,
    route: `${window.location.pathname}${window.location.search}`,
    user,
    message,
    topFrame,
    stack: error.stack,
    browser: {
      userAgent: navigator.userAgent,
      language: navigator.language,
      viewport: `${window.innerWidth}x${window.innerHeight}`,
      devicePixelRatio: window.devicePixelRatio,
    },
  };
}

/**
 * How much text the QR may carry.
 *
 * The code is printed at 80px. Past roughly this much the modules get too small
 * to survive being screenshotted and re-photographed, which is exactly the path
 * this payload travels — so the full stack and the environment go in the
 * downloaded file instead, and this stays a pointer plus a signature.
 */
const QR_BUDGET = 240;

/**
 * Long opaque ids in the path, shortened.
 *
 * A route like `/c/<32 hex>` spends a quarter of the budget saying which chat
 * it was, which the full record already says and which nobody retypes off a QR
 * anyway — whereas the file and line it crashed on is the whole point of
 * scanning. The shape of the route survives; the id is elided to its head.
 */
function shortenRoute(route: string): string {
  return route.replace(/\/([0-9a-f]{12,}|[\w-]{24,})(?=\/|$)/gi, (_, seg: string) => `/${seg.slice(0, 8)}…`);
}

/** Compact, line-oriented, and readable as plain text if the scanner just prints it. */
export function buildQrPayload(d: ErrorDiagnostics): string {
  const lines = [
    `BS1|${d.traceId}|${d.errorCode}`,
    d.version,
    d.timestamp,
    shortenRoute(d.route),
    d.message,
    d.topFrame ? `@ ${d.topFrame}` : '',
  ].filter(Boolean);

  // Trim the message and frame rather than dropping a line: the identifiers at
  // the top are what makes the rest findable, so they are never the ones cut.
  let payload = lines.join('\n');
  if (payload.length > QR_BUDGET) {
    const head = lines.slice(0, 4).join('\n');
    const room = Math.max(0, QR_BUDGET - head.length - 2);
    payload = `${head}\n${lines.slice(4).join('\n').slice(0, room)}`;
  }
  return payload;
}

/** The human-readable version of the same thing, for the clipboard. */
export function buildCopyText(d: ErrorDiagnostics, labels: Record<string, string>): string {
  return [
    `${labels.traceId}: ${d.traceId}`,
    `${labels.errorCode}: ${d.errorCode}`,
    `${labels.time}: ${d.timestamp}`,
    `${labels.version}: ${d.version}`,
    `${labels.route}: ${d.route}`,
    d.user ? `${labels.user}: ${d.user}` : '',
    '',
    d.message,
    d.stack ?? '',
  ]
    .filter((line) => line !== undefined)
    .join('\n');
}

/** Everything, including what the QR had to leave out. */
export function buildLogFile(d: ErrorDiagnostics): string {
  return JSON.stringify(d, null, 2);
}

export function buildLogFileName(d: ErrorDiagnostics): string {
  return `bisheng-error-${d.errorCode}-${d.traceId.slice(0, 8)}.json`;
}
