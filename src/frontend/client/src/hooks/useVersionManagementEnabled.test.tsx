import { renderHook } from "@testing-library/react";
import { useAiAccessUiEnabled } from "./useVersionManagementEnabled";

let mockConfig: { ai_access_ui_external_ids?: string[] } | undefined;
let mockUser: { id: string; external_id?: string | null } | undefined;

jest.mock("recoil", () => ({
  useRecoilValue: () => mockConfig,
}));
jest.mock("~/pages/appChat/store/atoms", () => ({
  bishengConfState: {},
}));
jest.mock("~/hooks/AuthContext", () => ({
  useAuthContext: () => ({ user: mockUser }),
}));

beforeEach(() => {
  mockConfig = { ai_access_ui_external_ids: ["0012", "employee-34"] };
  mockUser = { id: "99", external_id: "0012" };
});

it("shows entries by external_id even when the internal user ID differs", () => {
  const { result } = renderHook(() => useAiAccessUiEnabled());
  expect(result.current).toBe(true);
});

it.each([undefined, null, "", "12", "EMPLOYEE-34", "unlisted"])(
  "hides entries for an absent or unlisted external_id: %s",
  (external_id) => {
    mockUser = { id: "0012", external_id };
    const { result } = renderHook(() => useAiAccessUiEnabled());
    expect(result.current).toBe(false);
  },
);

it.each([undefined, {}, { ai_access_ui_external_ids: [] }])(
  "hides entries until a nonempty allowlist is loaded: %s",
  (config) => {
    mockConfig = config;
    const { result } = renderHook(() => useAiAccessUiEnabled());
    expect(result.current).toBe(false);
  },
);

it("updates visibility when the user changes or logs out", () => {
  const { result, rerender } = renderHook(() => useAiAccessUiEnabled());
  expect(result.current).toBe(true);
  mockUser = { id: "99", external_id: "unlisted" };
  rerender();
  expect(result.current).toBe(false);
  mockUser = { id: "99", external_id: "employee-34" };
  rerender();
  expect(result.current).toBe(true);
  mockUser = undefined;
  rerender();
  expect(result.current).toBe(false);
});

it("hides entries after the refreshed configuration removes the user", () => {
  const { result, rerender } = renderHook(() => useAiAccessUiEnabled());
  expect(result.current).toBe(true);
  mockConfig = { ai_access_ui_external_ids: ["employee-34"] };
  rerender();
  expect(result.current).toBe(false);
});
