/**
 * @jest-environment node
 */
import { createHash, randomBytes } from 'crypto';
import { sha256Hex, sha256HexOfBytes } from './sha256';

const nodeDigest = (bytes: Uint8Array): string => createHash('sha256').update(bytes).digest('hex');

describe('sha256HexOfBytes (non-secure-context fallback)', () => {
  it('matches the published vectors', () => {
    expect(sha256HexOfBytes(new Uint8Array())).toBe(
      'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
    );
    expect(sha256HexOfBytes(new TextEncoder().encode('abc'))).toBe(
      'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad',
    );
    expect(
      sha256HexOfBytes(new TextEncoder().encode('abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq')),
    ).toBe('248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1');
  });

  // Every block boundary and length word: a padding bug shows up as one wrong block.
  it.each([0, 1, 55, 56, 57, 63, 64, 65, 119, 120, 128, 1000, 100000])(
    'matches Node crypto for %i random bytes',
    (length) => {
      const bytes = new Uint8Array(randomBytes(length));
      expect(sha256HexOfBytes(bytes)).toBe(nodeDigest(bytes));
    },
  );

  it('hashes multibyte and binary content identically', () => {
    const bytes = new Uint8Array(randomBytes(4096));
    for (let index = 0; index < bytes.length; index += 1) bytes[index] = index % 256;
    expect(sha256HexOfBytes(bytes)).toBe(nodeDigest(bytes));
    expect(sha256HexOfBytes(new TextEncoder().encode('ünïcode ✓ 🎉'))).toBe(
      nodeDigest(new TextEncoder().encode('ünïcode ✓ 🎉')),
    );
  });

  it('does not mutate the input', () => {
    const bytes = new Uint8Array([1, 2, 3, 4]);
    const before = Array.from(bytes);
    sha256HexOfBytes(bytes);
    expect(Array.from(bytes)).toEqual(before);
  });
});

describe('sha256Hex', () => {
  const blob = (text: string) => ({ arrayBuffer: async () => new TextEncoder().encode(text).buffer }) as Blob;

  it('uses Web Crypto when the page is a secure context', async () => {
    const calls: string[] = [];
    const original = globalThis.crypto;
    Object.defineProperty(globalThis, 'crypto', {
      configurable: true,
      value: {
        ...original,
        subtle: {
          digest: async (_algorithm: string, data: Uint8Array) => {
            calls.push('subtle');
            return nodeDigest(data).match(/../g)!.map((pair) => parseInt(pair, 16));
          },
        },
      },
    });
    try {
      await expect(sha256Hex(blob('abc'))).resolves.toBe(
        'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad',
      );
      expect(calls).toEqual(['subtle']);
    } finally {
      Object.defineProperty(globalThis, 'crypto', { configurable: true, value: original });
    }
  });

  it('falls back when crypto.subtle is undefined (plain HTTP origin)', async () => {
    const original = globalThis.crypto;
    Object.defineProperty(globalThis, 'crypto', {
      configurable: true,
      value: { getRandomValues: original.getRandomValues.bind(original) },
    });
    try {
      await expect(sha256Hex(blob('abc'))).resolves.toBe(
        'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad',
      );
    } finally {
      Object.defineProperty(globalThis, 'crypto', { configurable: true, value: original });
    }
  });

  it('falls back when a broken subtle rejects', async () => {
    const original = globalThis.crypto;
    Object.defineProperty(globalThis, 'crypto', {
      configurable: true,
      value: {
        ...original,
        subtle: {
          digest: async () => {
            throw new Error('Operation is not supported');
          },
        },
      },
    });
    try {
      await expect(sha256Hex(blob('abc'))).resolves.toBe(
        'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad',
      );
    } finally {
      Object.defineProperty(globalThis, 'crypto', { configurable: true, value: original });
    }
  });
});
