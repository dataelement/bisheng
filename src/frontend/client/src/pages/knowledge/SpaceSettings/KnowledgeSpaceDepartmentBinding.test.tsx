import type { ReactNode } from "react";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  getSpaceInfoApi,
  getKnowledgeSpaceAutoTagVisibilityApi,
  SpaceRole,
  VisibilityType,
} from "~/api/knowledge";
import type { KnowledgeSpace } from "~/api/knowledge";
import { getMyResourcePermissions } from "~/api/permission";
import { useKnowledgeSpaceSettingsForm } from "./useKnowledgeSpaceSettingsForm";

jest.mock("~/api/knowledge");
jest.mock("~/api/permission");
jest.mock("~/utils", () => ({ generateUUID: () => "settings-test-id" }));

const mockInfo = jest.mocked(getSpaceInfoApi);

function space(binding: Partial<KnowledgeSpace>): KnowledgeSpace {
  return {
    id: "42",
    name: "department-named normal space",
    visibility: VisibilityType.APPROVAL,
    creator: "Creator",
    creatorId: "1",
    memberCount: 1,
    fileCount: 0,
    totalFileCount: 0,
    role: SpaceRole.ADMIN,
    isPinned: false,
    createdAt: "",
    updatedAt: "",
    tags: [],
    isReleased: true,
    ...binding,
  };
}

function wrapper({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider client={new QueryClient()}>
      {children}
    </QueryClientProvider>
  );
}

describe("knowledge settings uses real department binding metadata", () => {
  beforeEach(() => {
    jest
      .mocked(getKnowledgeSpaceAutoTagVisibilityApi)
      .mockResolvedValue({ visible: false });
    jest.mocked(getMyResourcePermissions).mockResolvedValue({
      mode: "CUSTOM",
      actions: ["edit"],
      sources: [],
      roster_complete: true,
    });
  });

  it.each([
    [{ departmentId: 8, spaceKind: "normal" }, true],
    [{ spaceKind: "department" }, true],
    [{ spaceKind: "normal" }, false],
  ] as const)(
    "recognizes binding %j rather than inferring it from the name",
    async (binding, expected) => {
      mockInfo.mockResolvedValue(space(binding));
      const { result } = renderHook(() => useKnowledgeSpaceSettingsForm("42"), {
        wrapper,
      });
      await waitFor(() => expect(result.current.loading).toBe(false));
      expect(result.current.loadError).toBeNull();
      expect(result.current.isDepartmentSpace).toBe(expected);
    },
  );

  it("does not retain the department restriction after navigating to a normal space", async () => {
    mockInfo
      .mockResolvedValueOnce(space({ departmentId: 8 }))
      .mockResolvedValueOnce(space({ id: "43" }));
    const { result, rerender } = renderHook(
      ({ id }) => useKnowledgeSpaceSettingsForm(id),
      {
        wrapper,
        initialProps: { id: "42" },
      },
    );
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.isDepartmentSpace).toBe(true);
    rerender({ id: "43" });
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.isDepartmentSpace).toBe(false);
  });
});
