import usePrefersMobileLayout from "./usePrefersMobileLayout";

let mockNarrow = true;
let mockEmbedded = false;
jest.mock("./useMediaQuery", () => ({
  __esModule: true,
  default: () => mockNarrow,
}));
jest.mock("~/components/Chat/desktopEmbedding", () => ({
  isDesktopEmbedded: () => mockEmbedded,
}));

it("uses the same available-space rule for Web and desktop hosts", () => {
  expect(usePrefersMobileLayout()).toBe(true);
  mockEmbedded = true;
  expect(usePrefersMobileLayout()).toBe(true);
  mockNarrow = false;
  expect(usePrefersMobileLayout()).toBe(false);
  mockEmbedded = false;
  expect(usePrefersMobileLayout()).toBe(false);
});
