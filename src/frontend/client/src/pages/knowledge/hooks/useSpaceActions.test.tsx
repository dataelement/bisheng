import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import {
    type GroupedKnowledgeSpaces,
    SpaceLevel,
    pinSpaceApi,
} from "~/api/knowledge";
import { useSpaceActions } from "./useSpaceActions";

jest.mock("~/api/knowledge", () => ({
    ...jest.requireActual("~/api/knowledge"),
    updateSpaceApi: jest.fn(),
    deleteSpaceApi: jest.fn(),
    unsubscribeSpaceApi: jest.fn(),
    pinSpaceApi: jest.fn(),
}));

jest.mock("~/Providers", () => ({
    useToastContext: () => ({ showToast: jest.fn() }),
}));

jest.mock("~/hooks", () => ({
    useLocalize: () => (key: string) => key,
}));

const groupedSpaces: GroupedKnowledgeSpaces = {
    publicSpaces: [],
    departmentSpaces: [],
    teamSpaces: [],
    personalSpaces: [],
};

test("个人知识库置顶处理器不调用 API，也不执行乐观更新", async () => {
    const queryClient = new QueryClient({
        defaultOptions: { queries: { retry: false } },
    });
    const setQueryData = jest.spyOn(queryClient, "setQueryData");
    const onSpaceSelect = jest.fn();
    const wrapper = ({ children }: { children: ReactNode }) => (
        <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
    const { result } = renderHook(
        () => useSpaceActions({ groupedSpaces, onSpaceSelect }),
        { wrapper },
    );

    await act(async () => {
        await result.current.handlePinSpace("personal-1", true, SpaceLevel.PERSONAL);
    });

    expect(pinSpaceApi).not.toHaveBeenCalled();
    expect(setQueryData).not.toHaveBeenCalled();
    expect(onSpaceSelect).not.toHaveBeenCalled();
});
