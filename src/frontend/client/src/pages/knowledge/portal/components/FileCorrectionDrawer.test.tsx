import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { submitFileCorrection } from "~/api/fileCorrection";
import { FileCorrectionDrawer } from "./FileCorrectionDrawer";

jest.mock("~/api/fileCorrection", () => {
    const actual = jest.requireActual("~/api/fileCorrection");
    return {
        ...actual,
        submitFileCorrection: jest.fn(),
    };
});

const mockedSubmit = jest.mocked(submitFileCorrection);

function renderDrawer() {
    const onClose = jest.fn();
    const onSubmitted = jest.fn();
    const onError = jest.fn();
    render(
        <FileCorrectionDrawer
            fileId="201"
            fileName="制度.pdf"
            onClose={onClose}
            onSubmitted={onSubmitted}
            onError={onError}
        />,
    );
    return { onClose, onSubmitted, onError };
}

describe("FileCorrectionDrawer", () => {
    it("requires both fields before submit and posts the two-part payload", async () => {
        mockedSubmit.mockResolvedValue({
            correction_id: 1,
            file_id: 201,
            file_name: "制度.pdf",
            space_id: 20,
            content: "原文写错了日期",
            original_error: "原文写错了日期",
            corrected_content: "应为 2026-10-13",
            status: "pending",
        });
        const { onClose, onSubmitted } = renderDrawer();

        const submit = screen.getByRole("button", { name: "提交" });
        expect(submit).toBeDisabled();

        fireEvent.change(screen.getByRole("textbox", { name: "原文错误处" }), {
            target: { value: "原文写错了日期" },
        });
        expect(submit).toBeDisabled();

        fireEvent.change(screen.getByRole("textbox", { name: "纠正后内容" }), {
            target: { value: "应为 2026-10-13" },
        });
        expect(submit).toBeEnabled();

        fireEvent.click(submit);
        await waitFor(() => {
            expect(mockedSubmit).toHaveBeenCalledWith("201", {
                originalError: "原文写错了日期",
                correctedContent: "应为 2026-10-13",
            });
        });
        expect(onClose).toHaveBeenCalled();
        expect(onSubmitted).toHaveBeenCalled();
    });
});
