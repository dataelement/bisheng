import { describe, it, expect } from 'vitest';

describe('Vitest infrastructure', () => {
  it('runs a basic test', () => {
    expect(1 + 1).toBe(2);
  });

  it('supports async tests', async () => {
    const result = await Promise.resolve('hello');
    expect(result).toBe('hello');
  });
});
