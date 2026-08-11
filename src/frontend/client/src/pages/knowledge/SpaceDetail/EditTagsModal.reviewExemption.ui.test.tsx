/**
 * 标签免审 UI 交互测试：覆盖输入区样式、保存分流、提示 toast。
 * 对应产品矩阵中的前端可见行为（组件级 UI，不依赖联调栈）。
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { EditTagsModal } from "./EditTagsModal";
import {
    addSpaceTagApi,
    batchUpdateTagsApi,
    getKnowledgeSpaceReviewTagVisibilityApi,
    getSpaceTagsApi,
    lookupSpaceTagApi,
    updateFileTagsApi,
} from "~/api/knowledge";
import { useToastContext } from "~/Providers";

jest.mock("~/hooks", () => ({
    useLocalize: () => (key: string) => key,
}));

const mockShowToast = jest.fn();

jest.mock("~/Providers", () => ({
    useToastContext: jest.fn(),
}));

jest.mock("@tanstack/react-query", () => ({
    useQueryClient: () => ({ invalidateQueries: jest.fn() }),
}));

jest.mock("~/api/knowledge", () => {
    const actual = jest.requireActual("~/api/knowledge") as typeof import("~/api/knowledge");
    return {
        ...actual,
        getSpaceTagsApi: jest.fn(),
        getKnowledgeSpaceReviewTagVisibilityApi: jest.fn(),
        addSpaceTagApi: jest.fn(),
        lookupSpaceTagApi: jest.fn(),
        updateFileTagsApi: jest.fn(),
        batchUpdateTagsApi: jest.fn(),
    };
});

/** 在输入区找到已选标签 chip 的外层 span。 */
function findSelectedTagChip(name: string): HTMLElement {
    const dialog = screen.getByTestId("edit-tags-dialog-body");
    const input = dialog.querySelector("#tag-input");
    if (!input?.parentElement) {
        throw new Error("tag input container not found");
    }
    const chipText = within(input.parentElement as HTMLElement).getByText(name);
    const outer = chipText.closest("span.flex.items-center");
    if (!outer) {
        throw new Error(`selected tag chip not found: ${name}`);
    }
    return outer as HTMLElement;
}

/** 预置已选标签并等待输入区渲染。 */
async function renderWithSelectedTags(
    tags: Array<{ id: number; name: string; review_status?: number; resource_type?: string; business_type?: string }>,
    selectedIds: number[],
) {
    jest.mocked(getSpaceTagsApi).mockResolvedValue(tags as never);
    render(
        <EditTagsModal
            isOpen
            onClose={jest.fn()}
            spaceId="100"
            fileId="1"
            initialTagIds={selectedIds}
            initialTags={tags as never}
        />,
    );
    await waitFor(() => expect(screen.getByTestId("edit-tags-dialog")).toBeInTheDocument());
}

describe("EditTagsModal review exemption UI", () => {
    beforeEach(() => {
        jest.clearAllMocks();
        jest.mocked(useToastContext).mockReturnValue({ showToast: mockShowToast });
        jest.mocked(getKnowledgeSpaceReviewTagVisibilityApi).mockResolvedValue({ enabled: true });
        jest.mocked(lookupSpaceTagApi).mockResolvedValue(null);
        jest.mocked(getSpaceTagsApi).mockResolvedValue([]);
        jest.mocked(batchUpdateTagsApi).mockResolvedValue(undefined);
        jest.mocked(updateFileTagsApi).mockResolvedValue(undefined);
    });

    it("UI-EX-01: 已通过标签在输入区使用正常色（非待审灰字）", async () => {
        await renderWithSelectedTags(
            [
                {
                    id: 501,
                    name: "免审标签",
                    review_status: 1,
                    resource_type: "manual_tag",
                    business_type: "tag_library",
                },
            ],
            [501],
        );

        const chip = findSelectedTagChip("免审标签");
        expect(chip.className).toContain("text-[#4e5969]");
        expect(chip.className).not.toContain("text-[#c9cdd4]");
    });

    it("UI-EX-02: 待审标签在输入区使用待审灰字样式", async () => {
        await renderWithSelectedTags(
            [
                {
                    id: 502,
                    name: "待审标签",
                    review_status: 0,
                    resource_type: "manual_tag",
                    business_type: "tag_library",
                },
            ],
            [502],
        );

        const chip = findSelectedTagChip("待审标签");
        expect(chip.className).toContain("text-[#c9cdd4]");
    });

    it("UI-EX-03: API 省略 review_status 时按待审展示并保存到 review_tag_ids", async () => {
        const user = userEvent.setup();
        jest.mocked(addSpaceTagApi).mockResolvedValue({
            id: 503,
            name: "缺省状态",
            business_type: "tag_library",
            resource_type: "manual_tag",
        });

        render(
            <EditTagsModal isOpen onClose={jest.fn()} spaceId="100" fileId="1" initialTagIds={[]} />,
        );

        await waitFor(() => expect(screen.getByRole("textbox")).not.toBeDisabled());
        await user.type(screen.getByRole("textbox"), "缺省状态");
        await user.keyboard("{Enter}");
        await user.click(screen.getByText("com_knowledge.confirm"));

        await waitFor(() => {
            expect(updateFileTagsApi).toHaveBeenCalledWith("100", "1", [], [503]);
        });
    });

    it("UI-EX-04: 免审与待审混选时分桶保存", async () => {
        const user = userEvent.setup();
        jest.mocked(addSpaceTagApi)
            .mockResolvedValueOnce({
                id: 601,
                name: "免审A",
                review_status: 1,
                resource_type: "manual_tag",
                business_type: "tag_library",
            })
            .mockResolvedValueOnce({
                id: 602,
                name: "待审B",
                review_status: 0,
                resource_type: "manual_tag",
                business_type: "tag_library",
            });

        render(
            <EditTagsModal isOpen onClose={jest.fn()} spaceId="100" fileId="1" initialTagIds={[]} />,
        );

        await waitFor(() => expect(screen.getByRole("textbox")).not.toBeDisabled());
        const input = screen.getByRole("textbox");
        await user.type(input, "免审A");
        await user.keyboard("{Enter}");
        await user.type(input, "待审B");
        await user.keyboard("{Enter}");
        await user.click(screen.getByText("com_knowledge.confirm"));

        await waitFor(() => {
            expect(updateFileTagsApi).toHaveBeenCalledWith("100", "1", [601], [602]);
        });
    });

    it("UI-EX-05: 免审保存不弹出 under_review 提示", async () => {
        const user = userEvent.setup();
        jest.mocked(addSpaceTagApi).mockResolvedValue({
            id: 701,
            name: "直接入库",
            review_status: 1,
            resource_type: "manual_tag",
            business_type: "tag_library",
        });

        render(
            <EditTagsModal isOpen onClose={jest.fn()} spaceId="100" fileId="1" initialTagIds={[]} />,
        );

        await waitFor(() => expect(screen.getByRole("textbox")).not.toBeDisabled());
        await user.type(screen.getByRole("textbox"), "直接入库");
        await user.keyboard("{Enter}");
        await user.click(screen.getByText("com_knowledge.confirm"));

        await waitFor(() => expect(updateFileTagsApi).toHaveBeenCalled());
        expect(mockShowToast).not.toHaveBeenCalledWith({
            message: "com_knowledge.tag_under_review",
            status: "warning",
        });
    });

    it("UI-EX-06: lookup 命中待审标签时提示 already_under_review 且不创建", async () => {
        const user = userEvent.setup();
        jest.mocked(lookupSpaceTagApi).mockResolvedValue({
            id: 801,
            name: "已有待审",
            review_status: 0,
            resource_type: "manual_tag",
        });

        render(
            <EditTagsModal isOpen onClose={jest.fn()} spaceId="100" fileId="1" initialTagIds={[]} />,
        );

        await waitFor(() => expect(screen.getByRole("textbox")).not.toBeDisabled());
        await user.type(screen.getByRole("textbox"), "已有待审");
        await user.keyboard("{Enter}");

        await waitFor(() => {
            expect(mockShowToast).toHaveBeenCalledWith({
                message: "com_knowledge.tag_already_under_review",
                status: "warning",
            });
        });
        expect(addSpaceTagApi).not.toHaveBeenCalled();
    });

    it("UI-EX-07: 批量模式免审标签写入 tag_ids", async () => {
        const user = userEvent.setup();
        jest.mocked(addSpaceTagApi).mockResolvedValue({
            id: 901,
            name: "批量免审",
            review_status: 1,
            resource_type: "manual_tag",
            business_type: "tag_library",
        });

        render(
            <EditTagsModal
                isOpen
                onClose={jest.fn()}
                spaceId="100"
                fileIds={["10", "11"]}
                initialTagIds={[]}
            />,
        );

        await waitFor(() => expect(screen.getByRole("textbox")).not.toBeDisabled());
        await user.type(screen.getByRole("textbox"), "批量免审");
        await user.keyboard("{Enter}");
        await user.click(screen.getByText("com_knowledge.confirm"));

        await waitFor(() => expect(addSpaceTagApi).toHaveBeenCalled());
        await waitFor(() => {
            expect(batchUpdateTagsApi).toHaveBeenCalledWith(
                "100",
                expect.objectContaining({
                    file_ids: [10, 11],
                    tag_ids: [901],
                    review_tag_ids: [],
                }),
            );
        });
    });

    it("UI-EX-08: 审核开启时展示手动标签审核提示文案", async () => {
        render(
            <EditTagsModal isOpen onClose={jest.fn()} spaceId="100" fileId="1" initialTagIds={[]} />,
        );

        await waitFor(() => {
            expect(screen.getByText("com_knowledge.manual_tag_review_hint")).toBeInTheDocument();
        });
    });
});
