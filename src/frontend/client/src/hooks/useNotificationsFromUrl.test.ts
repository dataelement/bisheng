import { renderHook, act } from "@testing-library/react";
import React from "react";
import { MemoryRouter } from "react-router-dom";
import { useNotificationsFromUrl } from "./useNotificationsFromUrl";

const wrap = (initialEntries: string[]) =>
  ({ children }: { children: React.ReactNode }) =>
    React.createElement(MemoryRouter, { initialEntries }, children);

describe("useNotificationsFromUrl", () => {
  it("returns closed state when no query param", () => {
    const { result } = renderHook(() => useNotificationsFromUrl(), {
      wrapper: wrap(["/"]),
    });
    expect(result.current.open).toBe(false);
    expect(result.current.focusedMessageId).toBeNull();
  });

  it("opens dialog and parses message-id from query", () => {
    const { result } = renderHook(() => useNotificationsFromUrl(), {
      wrapper: wrap(["/?open-notifications=1&message-id=42"]),
    });
    expect(result.current.open).toBe(true);
    expect(result.current.focusedMessageId).toBe(42);
  });

  it("setOpen(false) closes the dialog", () => {
    const { result } = renderHook(() => useNotificationsFromUrl(), {
      wrapper: wrap(["/?open-notifications=1"]),
    });
    expect(result.current.open).toBe(true);
    act(() => result.current.setOpen(false));
    expect(result.current.open).toBe(false);
  });
});
