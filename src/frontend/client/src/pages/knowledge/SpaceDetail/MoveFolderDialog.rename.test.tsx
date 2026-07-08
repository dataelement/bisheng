import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MoveFolderDialog } from "./MoveFolderDialog";
import {
    getSpaceChildrenApi,
    renameFolderApi,
    FileType,
} from "~/api/knowledge";
import { dispatchKnowledgeSpaceFilesRefresh } from "../hooks/useFileManager";

jest.mock("~/hooks", () => ({
    useLocalize: () => (key: string) => key,
}));

jest.mock("../hooks/useFileManager", () => ({
    dispatchKnowledgeSpaceFilesRefresh: jest.fn(),
}));

jest.mock("~/api/knowledge", () => {
    const actual = jest.requireActual("~/api/knowledge") as typeof import("~/api/knowledge");
    return {
        ...actual,
        getSpaceChildrenApi: jest.fn(),
        createFolderApi: jest.fn(),
        renameFolderApi: jest.fn(),
    };
});

const makeFolder = (id: string, name: string) =>
    ({ id, name, type: FileType.FOLDER } as any);

function mockChildren(list: any[]) {
    jest.mocked(getSpaceChildrenApi).mockResolvedValue({
        data: list,
        page_size: 200,
        has_more: false,
        next_cursor: null,
    } as any);
}

function renderDialog(overrides: Partial<Parameters<typeof MoveFolderDialog>[0]> = {}) {
    const props = {
        open: true,
        spaceId: "100",
        movingItemId: "999",
        movingItemType: "file" as const,
        onConfirm: jest.fn(),
        onCancel: jest.fn(),
        onFolderCreated: jest.fn(),
        ...overrides,
    };
    render(<MoveFolderDialog {...props} />);
    return props;
}

describe("MoveFolderDialog inline folder rename", () => {
    beforeEach(() => {
        jest.clearAllMocks();
        mockChildren([makeFolder("1", "旧名字")]);
        jest.mocked(renameFolderApi).mockResolvedValue(undefined as any);
    });

    it("点铅笔进入内联编辑，初值为当前名且被选中", async () => {
        renderDialog();
        expect(await screen.findByText("旧名字")).toBeInTheDocument();
        await userEvent.click(screen.getByTitle("com_knowledge.rename"));
        const input = screen.getByDisplayValue("旧名字") as HTMLInputElement;
        expect(input).toBeInTheDocument();
        // autoFocus + onFocus 全选
        expect(input).toHaveFocus();
    });

    it("改名回车 → 以正确参数调用 renameFolderApi 并触发刷新与重拉", async () => {
        const props = renderDialog();
        expect(await screen.findByText("旧名字")).toBeInTheDocument();
        await userEvent.click(screen.getByTitle("com_knowledge.rename"));
        const input = screen.getByDisplayValue("旧名字");
        await userEvent.clear(input);
        await userEvent.type(input, "新名字{Enter}");

        await waitFor(() => {
            expect(renameFolderApi).toHaveBeenCalledWith("100", "1", "新名字");
        });
        expect(dispatchKnowledgeSpaceFilesRefresh).toHaveBeenCalledWith("100");
        expect(props.onFolderCreated).toHaveBeenCalled();
        // 初次加载 + 重命名后重拉
        expect(jest.mocked(getSpaceChildrenApi).mock.calls.length).toBeGreaterThanOrEqual(2);
    });

    it("空名或与原名相同 → 不调用接口，收起编辑态", async () => {
        renderDialog();
        expect(await screen.findByText("旧名字")).toBeInTheDocument();

        // 未修改直接回车
        await userEvent.click(screen.getByTitle("com_knowledge.rename"));
        await userEvent.type(screen.getByDisplayValue("旧名字"), "{Enter}");
        expect(renameFolderApi).not.toHaveBeenCalled();

        // 清空后回车
        await userEvent.click(screen.getByTitle("com_knowledge.rename"));
        const input2 = screen.getByDisplayValue("旧名字");
        await userEvent.clear(input2);
        await userEvent.type(input2, "{Enter}");
        expect(renameFolderApi).not.toHaveBeenCalled();
    });

    it("Escape 取消编辑并恢复原名", async () => {
        renderDialog();
        expect(await screen.findByText("旧名字")).toBeInTheDocument();
        await userEvent.click(screen.getByTitle("com_knowledge.rename"));
        const input = screen.getByDisplayValue("旧名字");
        await userEvent.clear(input);
        await userEvent.type(input, "改一半{Escape}");
        expect(renameFolderApi).not.toHaveBeenCalled();
        expect(screen.getByText("旧名字")).toBeInTheDocument();
        expect(screen.queryByDisplayValue("改一半")).not.toBeInTheDocument();
    });

    it("点铅笔不会把该行选为移动目标（确认按钮仍禁用）", async () => {
        renderDialog();
        expect(await screen.findByText("旧名字")).toBeInTheDocument();
        await userEvent.click(screen.getByTitle("com_knowledge.rename"));
        const confirmBtn = screen.getByRole("button", { name: "com_bschoose_confirm" });
        expect(confirmBtn).toBeDisabled();
    });

    it("重命名与新建互斥：开始新建会关闭重命名", async () => {
        renderDialog();
        expect(await screen.findByText("旧名字")).toBeInTheDocument();
        await userEvent.click(screen.getByTitle("com_knowledge.rename"));
        expect(screen.getByDisplayValue("旧名字")).toBeInTheDocument();

        await userEvent.click(screen.getByText("com_knowledge.new_folder"));
        expect(screen.queryByDisplayValue("旧名字")).not.toBeInTheDocument();
        // 未改名的重命名被 blur 提交但因名字未变而跳过接口
        expect(renameFolderApi).not.toHaveBeenCalled();
        // 同一时刻只有一个内联输入（此时是新建输入框）
        expect(screen.getAllByRole("textbox")).toHaveLength(1);
    });

    it("在途重命名时禁用其他行的铅笔，避免并发重命名互相清空", async () => {
        mockChildren([makeFolder("1", "文件夹A"), makeFolder("2", "文件夹B")]);
        let resolveRename!: () => void;
        jest.mocked(renameFolderApi).mockReturnValue(
            new Promise<void>((res) => { resolveRename = () => res(); }) as any
        );
        renderDialog();
        expect(await screen.findByText("文件夹A")).toBeInTheDocument();

        // 开始重命名 A 并提交（进入在途状态）
        const pencils = screen.getAllByTitle("com_knowledge.rename");
        await userEvent.click(pencils[0]);
        const input = screen.getByDisplayValue("文件夹A");
        await userEvent.clear(input);
        await userEvent.type(input, "A改{Enter}");

        await waitFor(() => { expect(renameFolderApi).toHaveBeenCalled(); });

        // 在途期间：A 行是输入框（无铅笔），剩下的 B 行铅笔应被禁用
        const pencilsDuring = screen.getAllByTitle("com_knowledge.rename");
        expect(pencilsDuring[0]).toBeDisabled();

        // 结束在途请求：A 的编辑态正常关闭，无崩溃
        resolveRename();
        await waitFor(() => {
            expect(screen.queryByDisplayValue("A改")).not.toBeInTheDocument();
        });
    });
});
