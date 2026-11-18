import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { globalSearchSpaceFilesApi } from "~/api/knowledge";
import { GlobalSearchPanel } from "./GlobalSearchPanel";

jest.mock("~/api/knowledge", () => ({
    globalSearchSpaceFilesApi: jest.fn(),
}));

const mockedGlobalSearchApi = globalSearchSpaceFilesApi as jest.MockedFunction<typeof globalSearchSpaceFilesApi>;

describe("GlobalSearchPanel 知识库与文件统一搜索", () => {
    beforeEach(() => {
        jest.useFakeTimers();
        mockedGlobalSearchApi.mockReset();
    });

    afterEach(() => {
        jest.useRealTimers();
    });

    it("仅命中知识库名时正常展示库列表而不显示空状态，点击后回调并收起下拉", async () => {
        mockedGlobalSearchApi.mockResolvedValue({
            total: 0,
            page: 1,
            page_size: 30,
            data: [],
            space_total: 1,
            spaces: [
                {
                    space_id: 3534,
                    space_name: "销售财务中心(计划)",
                    space_level: "team_ks",
                    space_level_label: "科室知识库",
                    space_level_order: 2,
                },
            ],
        });

        const onSelectSpace = jest.fn();
        const onSelectFile = jest.fn();
        render(<GlobalSearchPanel onSelectSpace={onSelectSpace} onSelectFile={onSelectFile} />);

        const input = screen.getByPlaceholderText("搜索知识库或文件");
        fireEvent.change(input, { target: { value: "销售财务" } });
        jest.advanceTimersByTime(350);

        expect(await screen.findByText("知识库 (1)")).toBeInTheDocument();
        expect(screen.queryByText("未找到匹配的知识库或文件")).not.toBeInTheDocument();
        expect(screen.getByText("科室")).toBeInTheDocument();

        fireEvent.click(screen.getByRole("button", { name: /销售财务中心\(计划\)/ }));
        expect(onSelectSpace).toHaveBeenCalledWith(3534, "team_ks");
        await waitFor(() => {
            expect(screen.queryByText("知识库 (1)")).not.toBeInTheDocument();
        });
        expect((input as HTMLInputElement).value).toBe("销售财务");

        fireEvent.focus(input);
        expect(await screen.findByText("知识库 (1)")).toBeInTheDocument();
    });

    it("同时命中库与文件时支持预览文件及通过快捷按钮进入文件所属库", async () => {
        mockedGlobalSearchApi.mockResolvedValue({
            total: 1,
            page: 1,
            page_size: 30,
            space_total: 1,
            spaces: [
                {
                    space_id: 19,
                    space_name: "计划财务部",
                    space_level: "department",
                    space_level_label: "部门知识库",
                    space_level_order: 1,
                },
            ],
            data: [
                {
                    file_id: 101,
                    file_name: "财务制度.docx",
                    file_type_ext: "docx",
                    space_id: 19,
                    space_name: "计划财务部",
                    space_level: "department",
                    space_level_label: "部门知识库",
                    space_level_order: 1,
                    folder_path: ["制度"],
                },
            ],
        });

        const onSelectSpace = jest.fn();
        const onSelectFile = jest.fn();
        render(<GlobalSearchPanel onSelectSpace={onSelectSpace} onSelectFile={onSelectFile} />);

        fireEvent.change(screen.getByPlaceholderText("搜索知识库或文件"), { target: { value: "财务" } });
        jest.advanceTimersByTime(350);

        expect(await screen.findByText("知识库 (1)")).toBeInTheDocument();
        expect(screen.getByText("文件 (1)")).toBeInTheDocument();

        fireEvent.click(screen.getByRole("button", { name: /财务制度\.docx/ }));
        expect(onSelectFile).toHaveBeenCalledWith(19, 101, "财务制度.docx");

        fireEvent.click(screen.getByLabelText("进入计划财务部"));
        expect(onSelectSpace).toHaveBeenCalledWith(19, "department");
    });

    it("库与文件都无匹配时才展示空态提示", async () => {
        mockedGlobalSearchApi.mockResolvedValue({
            total: 0,
            page: 1,
            page_size: 30,
            data: [],
            space_total: 0,
            spaces: [],
        });

        render(<GlobalSearchPanel onSelectSpace={jest.fn()} onSelectFile={jest.fn()} />);

        fireEvent.change(screen.getByPlaceholderText("搜索知识库或文件"), { target: { value: "不存在的关键词" } });
        jest.advanceTimersByTime(350);

        expect(await screen.findByText("未找到匹配的知识库或文件")).toBeInTheDocument();
    });
});
