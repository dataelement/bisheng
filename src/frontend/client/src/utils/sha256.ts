/**
 * SHA-256 as lowercase hex, with a fallback for non-secure contexts.
 *
 * `crypto.subtle` only exists on a secure context. The client is routinely served
 * over plain HTTP on a LAN address (e.g. `http://192.168.106.107:3001`), where
 * `window.isSecureContext` is false and `crypto.subtle` is `undefined`. The
 * provider upload receipt protocol needs a client-side SHA-256 of the bytes before
 * the first write (it is part of the request identity and of the quota receipt),
 * so without a fallback every WeKnora upload failed as "not sent" without a single
 * byte leaving the browser. `crypto.getRandomValues` is *not* restricted, which is
 * why the rest of the app works on the same origin.
 *
 * Keep both paths byte-identical: the value is compared against the backend's
 * hashlib digest and is stored as the version receipt checksum.
 */

const K = new Uint32Array([
  0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
  0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
  0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
  0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
  0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
  0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
  0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
  0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
]);

const rotr = (value: number, bits: number): number => (value >>> bits) | (value << (32 - bits));

const toHex = (bytes: Uint8Array): string =>
  Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('');

/** Synchronous SHA-256 of raw bytes. Works without Web Crypto. */
export function sha256HexOfBytes(input: Uint8Array): string {
  const length = input.length;
  // 0x80 terminator + 8-byte big-endian bit length, rounded up to a 64-byte block.
  // (length + 9 + 63) >> 6 blocks: 55 bytes exactly fills one block, 56 needs two.
  const total = ((length + 9 + 63) >> 6) << 6;
  const buffer = new Uint8Array(total);
  buffer.set(input);
  buffer[length] = 0x80;
  const view = new DataView(buffer.buffer);
  // Bit length needs 64 bits: high word first, then the low 32 bits.
  view.setUint32(total - 8, Math.floor(length / 0x20000000));
  view.setUint32(total - 4, (length << 3) >>> 0);

  let h0 = 0x6a09e667;
  let h1 = 0xbb67ae85;
  let h2 = 0x3c6ef372;
  let h3 = 0xa54ff53a;
  let h4 = 0x510e527f;
  let h5 = 0x9b05688c;
  let h6 = 0x1f83d9ab;
  let h7 = 0x5be0cd19;
  const w = new Uint32Array(64);

  for (let offset = 0; offset < total; offset += 64) {
    for (let index = 0; index < 16; index += 1) {
      w[index] = view.getUint32(offset + index * 4);
    }
    for (let index = 16; index < 64; index += 1) {
      const s0 = rotr(w[index - 15], 7) ^ rotr(w[index - 15], 18) ^ (w[index - 15] >>> 3);
      const s1 = rotr(w[index - 2], 17) ^ rotr(w[index - 2], 19) ^ (w[index - 2] >>> 10);
      w[index] = (w[index - 16] + s0 + w[index - 7] + s1) >>> 0;
    }

    let a = h0;
    let b = h1;
    let c = h2;
    let d = h3;
    let e = h4;
    let f = h5;
    let g = h6;
    let h = h7;

    for (let index = 0; index < 64; index += 1) {
      const s1 = rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25);
      const choice = (e & f) ^ (~e & g);
      const temp1 = (h + s1 + choice + K[index] + w[index]) >>> 0;
      const s0 = rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22);
      const majority = (a & b) ^ (a & c) ^ (b & c);
      const temp2 = (s0 + majority) >>> 0;
      h = g;
      g = f;
      f = e;
      e = (d + temp1) >>> 0;
      d = c;
      c = b;
      b = a;
      a = (temp1 + temp2) >>> 0;
    }

    h0 = (h0 + a) >>> 0;
    h1 = (h1 + b) >>> 0;
    h2 = (h2 + c) >>> 0;
    h3 = (h3 + d) >>> 0;
    h4 = (h4 + e) >>> 0;
    h5 = (h5 + f) >>> 0;
    h6 = (h6 + g) >>> 0;
    h7 = (h7 + h) >>> 0;
  }

  const digest = new Uint8Array(32);
  const out = new DataView(digest.buffer);
  [h0, h1, h2, h3, h4, h5, h6, h7].forEach((word, index) => out.setUint32(index * 4, word));
  return toHex(digest);
}

/**
 * SHA-256 of a blob as lowercase hex.
 *
 * Prefers Web Crypto (native, fast) and falls back to the pure implementation
 * when the page is not a secure context. A failing `subtle.digest` falls back too:
 * a preparation step must not be the reason a file cannot be sent.
 */
export async function sha256Hex(blob: Blob): Promise<string> {
  const bytes = new Uint8Array(await blob.arrayBuffer());
  const subtle = globalThis.crypto?.subtle;
  if (subtle) {
    try {
      return toHex(new Uint8Array(await subtle.digest('SHA-256', bytes)));
    } catch {
      // Fall through to the portable implementation.
    }
  }
  return sha256HexOfBytes(bytes);
}
