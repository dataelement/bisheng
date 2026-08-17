import { renderHook } from "@testing-library/react";
import { useCreateChannelForm } from "./useCreateChannelForm";

jest.mock("~/hooks", () => ({
  useLocalize: () => (key: string) => key,
}));

describe("useCreateChannelForm", () => {
  it("keeps the edit-form initializer stable across rerenders", () => {
    const { result, rerender } = renderHook(() => useCreateChannelForm());
    const initialInitializer = result.current.initFromChannel;

    rerender();

    expect(result.current.initFromChannel).toBe(initialInitializer);
  });
});
