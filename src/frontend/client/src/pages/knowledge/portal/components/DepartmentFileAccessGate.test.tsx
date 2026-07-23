import { fireEvent, render, screen } from "@testing-library/react";
import { DepartmentFileAccessGate } from "./DepartmentFileAccessGate";

describe("DepartmentFileAccessGate", () => {
    it("does not auto-submit and trims the reason before explicit apply", () => {
        const onApply = jest.fn();
        render(
            <DepartmentFileAccessGate
                access={{
                    spaceId: "10",
                    fileId: "20",
                    status: "approval_required",
                    contentAccess: "approval_required",
                    canDownload: false,
                    safeMetadata: {
                        file_name: "部门制度.pdf",
                        space_name: "炼钢部知识库",
                    },
                }}
                applying={false}
                error=""
                onApply={onApply}
                onOpenRequests={jest.fn()}
            />,
        );

        expect(onApply).not.toHaveBeenCalled();
        fireEvent.change(screen.getByLabelText("申请原因"), {
            target: { value: "  项目查阅  " },
        });
        fireEvent.click(screen.getByRole("button", { name: "提交查看申请" }));
        expect(onApply).toHaveBeenCalledWith("项目查阅");
    });

    it("shows pending state without an apply button", () => {
        render(
            <DepartmentFileAccessGate
                access={{
                    spaceId: "10",
                    fileId: "20",
                    status: "pending",
                    contentAccess: "approval_required",
                    canDownload: false,
                    instanceId: 30,
                    safeMetadata: { file_name: "部门制度.pdf" },
                }}
                applying={false}
                error=""
                onApply={jest.fn()}
                onOpenRequests={jest.fn()}
            />,
        );

        expect(screen.getByText("查看申请审批中")).toBeInTheDocument();
        expect(screen.queryByRole("button", { name: "提交查看申请" })).not.toBeInTheDocument();
        expect(screen.getByRole("button", { name: "打开我的申请" })).toBeInTheDocument();
    });
});
