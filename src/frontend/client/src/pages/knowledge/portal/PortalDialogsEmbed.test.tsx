import { act, fireEvent, render, screen } from "@testing-library/react";
import PortalDialogsEmbed from "./PortalDialogsEmbed";

jest.mock("~/components/approval/ApprovalCenterDialog", () => ({
    ApprovalCenterDialog: ({ open, target, onOpenChange }: any) =>
        open ? (
            <div data-testid="approval-center-dialog">
                审批中心:{target?.tab}
                <button data-testid="close-approval" onClick={() => onOpenChange(false)}>
                    关闭
                </button>
            </div>
        ) : null,
}));

jest.mock("~/components/NotificationsDialog", () => ({
    NotificationsDialog: ({ open, onOpenChange }: any) =>
        open ? (
            <div data-testid="notifications-dialog">
                消息
                <button data-testid="close-notifications" onClick={() => onOpenChange(false)}>
                    关闭
                </button>
            </div>
        ) : null,
}));

function postFromParent(type: string) {
    act(() => {
        window.dispatchEvent(new MessageEvent("message", { data: { type } }));
    });
}

describe("PortalDialogsEmbed", () => {
    it("opens the approval center for the my-tasks message", () => {
        render(<PortalDialogsEmbed />);
        postFromParent("shougang-portal:open-approval-tasks");
        expect(screen.getByTestId("approval-center-dialog")).toHaveTextContent("my_tasks");
    });

    it("opens the notifications dialog for the notifications message", () => {
        render(<PortalDialogsEmbed />);
        postFromParent("shougang-portal:open-notifications");
        expect(screen.getByTestId("notifications-dialog")).toBeInTheDocument();
    });

    it("notifies the parent when the last open dialog closes", () => {
        const postSpy = jest.spyOn(window.parent, "postMessage");
        render(<PortalDialogsEmbed />);
        postFromParent("shougang-portal:open-approval-tasks");

        postSpy.mockClear();
        fireEvent.click(screen.getByTestId("close-approval"));

        expect(postSpy).toHaveBeenCalledWith(
            { type: "shougang-portal:dialog-closed" },
            "*",
        );
        postSpy.mockRestore();
    });
});
