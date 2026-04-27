import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import KnowledgeSquare from "./KnowledgeSquare";
import { getJoinedSpacesApi, getSquareSpacesApi, SpaceRole, subscribeSpaceApi, VisibilityType } from "~/api/knowledge";

jest.mock("~/Providers", () => ({
  useToastContext: () => ({
    showToast: jest.fn(),
  }),
}));

jest.mock("~/hooks", () => ({
  useLocalize: () => (key: string) => {
    const dict: Record<string, string> = {
      "com_knowledge.explore_square": "知识广场",
      "com_knowledge.explore_more_spaces": "探索更多空间",
      "com_knowledge.search_space_placeholder": "搜索空间",
      "com_knowledge.no_matched_space": "暂无空间",
      "com_knowledge.reapply": "重新申请",
      "com_knowledge.join": "加入",
      "com_knowledge.pending": "待审批",
      "com_knowledge.joined": "已加入",
      "com_knowledge.no_description": "暂无描述",
      "com_knowledge.users_count": "用户",
      "com_knowledge.applied_to_join_space": "申请已发送",
      "com_subscription.articles": "篇内容",
    };
    return dict[key] || key;
  },
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
  getJoinedSpacesApi: jest.fn(),
  getSquareSpacesApi: jest.fn(),
  subscribeSpaceApi: jest.fn(),
}));

describe("KnowledgeSquare", () => {
  test("reapplies from rejected card state", async () => {
    const mockedGetSquareSpacesApi = jest.mocked(getSquareSpacesApi);
    const mockedGetJoinedSpacesApi = jest.mocked(getJoinedSpacesApi);
    const mockedSubscribeSpaceApi = jest.mocked(subscribeSpaceApi);
    const onSquareStatusChange = jest.fn();

    mockedGetSquareSpacesApi.mockResolvedValue({
      data: [
        {
          id: "space-1",
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
          squareStatus: "rejected",
          subscriptionStatus: "rejected",
        },
      ],
      total: 1,
    } as any);
    mockedGetJoinedSpacesApi.mockResolvedValue([]);
    mockedSubscribeSpaceApi.mockResolvedValue({ status: "pending", spaceId: "space-1" });

    render(
      <KnowledgeSquare
        statusOverride={{ "space-1": "rejected" }}
        onSquareStatusChange={onSquareStatusChange}
      />
    );

    fireEvent.click(await screen.findByRole("button", { name: "重新申请" }));

    await waitFor(() => {
      expect(mockedSubscribeSpaceApi).toHaveBeenCalledWith("space-1");
      expect(onSquareStatusChange).toHaveBeenCalledWith("space-1", "pending");
    });
  });
});
