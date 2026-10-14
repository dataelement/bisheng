import { fireEvent, render, screen } from "@testing-library/react";
import { PortalHeaderActions } from "./PortalHeaderActions";

const props = {
    canUpload: false,
    canCreateFolder: false,
    statusFilter: [],
    onOpenUploadDialog: jest.fn(),
    onOpenWebLinkDialog: jest.fn(),
    onShowUnavailable: jest.fn(),
    onCreateFolder: jest.fn(),
    onToggleStatusFilter: jest.fn(),
};

it("查看者不显示写操作，仍可筛选", () => {
    render(<PortalHeaderActions {...props} />);
    for (const name of ["上传", "网页链接", "新建文件夹"]) {
        expect(screen.queryByRole("button", { name })).not.toBeInTheDocument();
    }
    expect(screen.getByRole("button", { name: "筛选" })).toBeEnabled();
});

it("操作独立按权限显示，有权限时保留交互", () => {
    const { rerender } = render(<PortalHeaderActions {...props} canUpload />);
    fireEvent.click(screen.getByRole("button", { name: "上传" }));
    fireEvent.click(screen.getByRole("button", { name: "网页链接" }));
    expect(props.onOpenUploadDialog).toHaveBeenCalledTimes(1);
    expect(props.onOpenWebLinkDialog).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("button", { name: "新建文件夹" })).not.toBeInTheDocument();
    rerender(<PortalHeaderActions {...props} canCreateFolder />);
    expect(screen.queryByRole("button", { name: "上传" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "新建文件夹" }));
    expect(props.onCreateFolder).toHaveBeenCalledTimes(1);
});
