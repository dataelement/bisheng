import { useWelcomeTransition } from './useWelcomeTransition';

let mockDispose: (() => void) | undefined;
jest.mock('react', () => ({ useRef: () => ({ current: null }), useEffect: (setup: () => (() => void) | undefined) => { mockDispose = setup(); } }));
jest.mock('./desktopEmbedding', () => ({ isDesktopEmbedded: () => true }));

it('replaces pending title motion and releases it on unmount, honoring reduced motion', () => {
  let enter: (() => void) | undefined;
  let reduced = false;
  const cancel = jest.fn();
  const animate = jest.fn(() => ({ cancel }));
  window.addEventListener = jest.fn((_type, listener) => { enter = listener as () => void; });
  window.removeEventListener = jest.fn();
  window.matchMedia = jest.fn(() => ({ matches: reduced })) as unknown as typeof window.matchMedia;
  const element = { animate, getClientRects: () => [{}] } as unknown as HTMLHeadingElement;
  useWelcomeTransition({ current: element });
  enter?.();
  expect(animate).toHaveBeenCalledWith(expect.any(Array), expect.objectContaining({ duration: 180 }));
  enter?.();
  expect(cancel).toHaveBeenCalledTimes(1);
  reduced = true;
  enter?.();
  expect(animate).toHaveBeenCalledTimes(2);
  mockDispose?.();
  expect(window.removeEventListener).toHaveBeenCalledWith('dsh:welcome-enter', enter);
  expect(cancel).toHaveBeenCalledTimes(3);
});
