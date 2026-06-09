import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { KnowledgeSpacePreviewDrawer } from "./KnowledgeSpacePreviewDrawer";
import { SpaceRole, VisibilityType, getJoinedSpacesApi, getSpaceChildrenApi, getSpaceInfoApi, subscribeSpaceApi } from "~/api/knowledge";

jest.mock("~/Providers", () => ({
  useToastContext: () => ({
    showToast: jest.fn(),
  }),
}));

jest.mock("~/hooks", () => ({
  useLocalize: () => (key: string) => {
    const dict: Record<string, string> = {
      "com_knowledge.loading": "加载中",
      "com_knowledge.join": "加入",
      "com_knowledge.joined": "已加入",
      "com_knowledge.space_invalid_or_deleted": "该知识库已失效或被删除",
      "com_knowledge.collapse_drawer": "收起",
      "com_knowledge.close": "关闭",
      "com_knowledge.articles_count": "篇内容",
      "com_knowledge.users_count": "用户",
      "com_knowledge.space_view_requires_join": "加入后可查看详情",
      "com_knowledge.exit_space_short": "退出知识库",
      "com_knowledge.withdraw_application": "撤回申请",
      "com_knowledge.reapply": "重新申请",
    };
    return dict[key] || key;
	  },
	  usePrefersMobileLayout: () => false,
	  useScrollRevealRef: () => ({ current: null }),
	}));

jest.mock("./SpaceDetail/FileCard", () => ({
  FileCard: () => <div data-testid="file-card" />,
}));

jest.mock("~/components/ui/Sheet", () => ({
  Sheet: ({ open, children }: any) => (open ? <div data-testid="sheet">{children}</div> : null),
  SheetContent: ({ children }: any) => <div>{children}</div>,
  SheetHeader: ({ children }: any) => <div>{children}</div>,
  SheetTitle: ({ children }: any) => <div>{children}</div>,
}));

jest.mock("~/components/ui/Tooltip2", () => ({
  Tooltip: ({ children }: any) => <>{children}</>,
  TooltipTrigger: ({ children }: any) => <>{children}</>,
  TooltipContent: ({ children }: any) => <div>{children}</div>,
}));

jest.mock("~/components/ui/Button", () => ({
  Button: ({ children, ...props }: any) => <button {...props}>{children}</button>,
}));

jest.mock("~/api/knowledge", () => ({
  SpaceRole: {
    CREATOR: "creator",
    ADMIN: "admin",
    MEMBER: "member",
  },
  VisibilityType: {
    PUBLIC: "public",
    PRIVATE: "private",
    APPROVAL: "approval",
  },
  SPACE_CHILDREN_STATUS_SUCCESS_ONLY: [2],
  getJoinedSpacesApi: jest.fn(),
  getSpaceChildrenApi: jest.fn(),
  getSpaceInfoApi: jest.fn(),
  subscribeSpaceApi: jest.fn(),
  unsubscribeSpaceApi: jest.fn(),
}));

describe("KnowledgeSpacePreviewDrawer", () => {
  test("keeps fallback detail visible for unjoined square spaces when info fetch is denied", async () => {
    const mockedGetSpaceInfoApi = jest.mocked(getSpaceInfoApi);
    const mockedGetSpaceChildrenApi = jest.mocked(getSpaceChildrenApi);
    mockedGetSpaceChildrenApi.mockResolvedValue({ data: [], total: 0 });
    mockedGetSpaceInfoApi.mockRejectedValue(new Error("permission denied"));

    const baseSpace = {
      id: "space-1",
      name: "未加入空间",
      description: "这是广场卡片上的摘要",
      icon: "",
      visibility: VisibilityType.PUBLIC,
      creator: "Zhou",
      creatorId: "u-1",
      memberCount: 3,
      fileCount: 8,
      totalFileCount: 8,
      role: SpaceRole.MEMBER,
      isPinned: false,
      createdAt: "",
      updatedAt: "",
      tags: [],
      isReleased: true,
      isFollowed: false,
      isPending: false,
    };

    function Wrapper() {
      const [statusMap, setStatusMap] = useState<Record<string, "join" | "joined" | "pending" | "rejected">>({});

      return (
        <KnowledgeSpacePreviewDrawer
          spaceId={baseSpace.id}
          initialSpace={{
            ...baseSpace,
            squareStatus: statusMap[baseSpace.id],
          }}
          open
          onOpenChange={() => undefined}
          onSquareStatusChange={(id, status) => {
            setStatusMap((prev) => ({
              ...prev,
              [id]: status,
            }));
          }}
        />
      );
    }

    render(<Wrapper />);

    await waitFor(() => {
      expect(screen.getByText("未加入空间")).toBeInTheDocument();
    });

    await waitFor(() => {
      expect(screen.getAllByText("这是广场卡片上的摘要").length).toBeGreaterThan(0);
    });

    await new Promise((resolve) => setTimeout(resolve, 30));

    expect(mockedGetSpaceInfoApi).toHaveBeenCalledTimes(1);
  });

  test("loads files for unjoined public square spaces", async () => {
    const mockedGetSpaceInfoApi = jest.mocked(getSpaceInfoApi);
    const mockedGetSpaceChildrenApi = jest.mocked(getSpaceChildrenApi);
    const publicSpace = {
      id: "space-public",
      name: "公开空间",
      description: "公开可浏览",
      icon: "",
      visibility: VisibilityType.PUBLIC,
      creator: "Zhou",
      creatorId: "u-1",
      memberCount: 3,
      fileCount: 1,
      totalFileCount: 1,
      role: SpaceRole.MEMBER,
      isPinned: false,
      createdAt: "",
      updatedAt: "",
      tags: [],
      isReleased: true,
      isFollowed: false,
      isPending: false,
    };

    mockedGetSpaceInfoApi.mockResolvedValue(publicSpace as any);
    mockedGetSpaceChildrenApi.mockResolvedValue({
      data: [
        {
          id: "file-1",
          name: "公开文件.pdf",
          type: "pdf",
          tags: [],
          path: "公开文件.pdf",
          spaceId: "space-public",
          createdAt: "",
          updatedAt: "",
        },
      ],
      total: 1,
    } as any);

    render(
      <KnowledgeSpacePreviewDrawer
        spaceId={publicSpace.id}
        initialSpace={publicSpace as any}
        open
        onOpenChange={() => undefined}
      />
    );

    await waitFor(() => {
      expect(mockedGetSpaceChildrenApi).toHaveBeenCalledWith(
        expect.objectContaining({
          space_id: "space-public",
          file_status: [2],
        })
      );
      expect(screen.getByTestId("file-card")).toBeInTheDocument();
    });

    expect(screen.queryByText("加入后可查看详情")).not.toBeInTheDocument();
  });

  test("allows reapplying from rejected preview state", async () => {
    const mockedGetSpaceInfoApi = jest.mocked(getSpaceInfoApi);
    const mockedGetJoinedSpacesApi = jest.mocked(getJoinedSpacesApi);
    const mockedSubscribeSpaceApi = jest.mocked(subscribeSpaceApi);
    const rejectedSpace = {
      id: "space-2",
      name: "审批空间",
      description: "需要审批",
      icon: "",
      visibility: VisibilityType.APPROVAL,
      creator: "Zhou",
      creatorId: "u-1",
      memberCount: 3,
      fileCount: 8,
      totalFileCount: 8,
      role: SpaceRole.MEMBER,
      isPinned: false,
      createdAt: "",
      updatedAt: "",
      tags: [],
      isReleased: true,
      isFollowed: false,
      isPending: false,
      subscriptionStatus: "rejected",
    };

    mockedGetSpaceInfoApi.mockResolvedValue(rejectedSpace as any);
    mockedGetJoinedSpacesApi.mockResolvedValue([]);
    mockedSubscribeSpaceApi.mockResolvedValue({ status: "pending", spaceId: "space-2" });

    render(
      <KnowledgeSpacePreviewDrawer
        spaceId={rejectedSpace.id}
        initialSpace={rejectedSpace as any}
        open
        onOpenChange={() => undefined}
      />
    );

    fireEvent.click(await screen.findByRole("button", { name: "重新申请" }));

    await waitFor(() => {
      expect(mockedSubscribeSpaceApi).toHaveBeenCalledWith("space-2");
    });
  });
});
