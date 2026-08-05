import { fireEvent, render, screen, within } from "@testing-library/react";
import { PortalFileCategoryDropdown } from "./PortalFileCategoryDropdown";

const groups = [
    {
        code: "STD",
        label: "标准规范",
        children: [
            {
                code: "STD",
                label: "标准规范",
                parentCode: "STD",
                parentLabel: "标准规范",
            },
        ],
    },
    {
        code: "RPT",
        label: "报告",
        children: [
            {
                code: "RPT",
                label: "报告",
                parentCode: "RPT",
                parentLabel: "报告",
            },
        ],
    },
];

describe("PortalFileCategoryDropdown", () => {
    it("portals the floating menu into the provided dialog layer instead of document.body", () => {
        const layer = document.createElement("div");
        layer.setAttribute("data-upload-records-menu-layer", "true");
        document.body.appendChild(layer);

        const onChange = jest.fn();
        render(
            <PortalFileCategoryDropdown
                variant="fileTable"
                menuPortalContainer={layer}
                groups={groups}
                value="STD"
                ariaLabel="修改文件分类"
                onChange={onChange}
            />,
        );

        fireEvent.click(screen.getByRole("button", { name: "修改文件分类 当前选择：标准规范 / 标准规范" }));

        const menu = within(layer).getByRole("tree", { name: "修改文件分类" });
        expect(menu).toBeInTheDocument();
        expect(menu.getAttribute("data-portal-file-category-menu")).toBe("true");
        expect(document.body.querySelector(":scope > [data-portal-file-category-menu='true']")).toBeNull();

        fireEvent.click(within(menu).getByRole("button", { name: "报告" }));
        fireEvent.click(within(menu).getByRole("button", { name: "报告 / 报告" }));

        expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ code: "RPT", parentCode: "RPT" }));

        layer.remove();
    });

    it("keeps body portal for fileTable when no dialog layer is provided", () => {
        render(
            <PortalFileCategoryDropdown
                variant="fileTable"
                groups={groups}
                value="STD"
                ariaLabel="修改文件分类"
                onChange={jest.fn()}
            />,
        );

        fireEvent.click(screen.getByRole("button", { name: "修改文件分类 当前选择：标准规范 / 标准规范" }));
        const menu = screen.getByRole("tree", { name: "修改文件分类" });
        expect(menu.parentElement).toBe(document.body);
    });
});
