import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { KnowledgeSpacePreviewDrawer } from "./KnowledgeSpacePreviewDrawer";
import { SpaceRole, VisibilityType, getJoinedSpacesApi, getSpaceInfoApi, subscribeSpaceApi } from "~/api/knowledge";

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
      "com_knowledge.space_invalid_or_deleted": "该知识空间已失效或被删除",
      "com_knowledge.collapse_drawer": "收起",
      "com_knowledge.close": "关闭",
      "com_knowledge.articles_count": "篇内容",
      "com_knowledge.users_count": "用户",
      "com_knowledge.space_view_requires_join": "加入后可查看详情",
      "com_knowledge.exit_space_short": "退出空间",
      "com_knowledge.withdraw_application": "撤回申请",
      "com_knowledge.reapply": "重新申请",
    };
    return dict[key] || key;
  },
  usePrefersMobileLayout: () => false,
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
