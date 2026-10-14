import { render, screen, waitFor } from "@testing-library/react";
import { getFileCorrection } from "~/api/fileCorrection";
import { FileCorrectionNotice } from "./FileCorrectionNotice";

jest.mock("~/api/fileCorrection", () => ({
    getFileCorrection: jest.fn(),
}));

const mockedGet = jest.mocked(getFileCorrection);

describe("FileCorrectionNotice", () => {
    it("shows two labeled blocks for a two-part correction", async () => {
        mockedGet.mockResolvedValue({
            correction_id: 9,
            file_id: 201,
            file_name: "制度.pdf",
            space_id: 20,
            content: "原文写错了日期",
            original_error: "原文写错了日期",
            corrected_content: "应为 2026-10-13",
            status: "pending",
        });

        render(<FileCorrectionNotice correctionId={9} />);

        expect(await screen.findByTestId("file-correction-original-error")).toHaveTextContent("原文写错了日期");
        expect(screen.getByTestId("file-correction-corrected-content")).toHaveTextContent("应为 2026-10-13");
        expect(screen.queryByText("纠错说明")).not.toBeInTheDocument();
    });

    it("keeps a single 纠错说明 block for legacy one-part records", async () => {
        mockedGet.mockResolvedValue({
            correction_id: 8,
            file_id: 201,
            file_name: "制度.pdf",
            space_id: 20,
            content: "这里有一个错字",
            original_error: null,
            corrected_content: null,
            status: "pending",
        });

        render(<FileCorrectionNotice correctionId={8} />);

        await waitFor(() => {
            expect(screen.getByTestId("file-correction-notice")).toHaveTextContent("这里有一个错字");
        });
        expect(screen.getByText("纠错说明")).toBeInTheDocument();
        expect(screen.queryByTestId("file-correction-original-error")).not.toBeInTheDocument();
    });
});
