import usePrefersMobileLayout from './usePrefersMobileLayout';

let mockNarrow = true;
let mockEmbedded = false;
jest.mock('./useMediaQuery', () => ({ __esModule: true, default: () => mockNarrow }));
jest.mock('~/components/Chat/desktopEmbedding', () => ({ isDesktopEmbedded: () => mockEmbedded }));

it('uses desktop pages inside the host and viewport-based layouts in the browser', () => {
  expect(usePrefersMobileLayout()).toBe(true);
  mockEmbedded = true;
  expect(usePrefersMobileLayout()).toBe(false);
  mockNarrow = false;
  expect(usePrefersMobileLayout()).toBe(false);
  mockEmbedded = false;
  expect(usePrefersMobileLayout()).toBe(false);
});
