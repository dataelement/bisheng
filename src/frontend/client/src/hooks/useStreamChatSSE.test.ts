/** @jest-environment node */

jest.mock('sse.js', () => ({ SSE: jest.fn() }));

import { createStreamEndGuard } from './useStreamChatSSE';

describe('stream end guard', () => {
  it('completes the caller only once when close and cleanup both finish the stream', () => {
    const onEnd = jest.fn();
    const safeEnd = createStreamEndGuard(onEnd);

    safeEnd();
    safeEnd();

    expect(onEnd).toHaveBeenCalledTimes(1);
  });
});
