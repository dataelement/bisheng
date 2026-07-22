import { useState } from "react";

import { fireEvent, render, screen } from "@/test/test-utils";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { DialogWithRepeatFiles } from "./DuplicateFileDialog";

const translations = {
    modalTitle: "文件重复提示",
    modalMessage: "请选择如何处理重复文件",
    keepOriginal: "不覆盖，保留原文件",
    override: "覆盖",
};

function DialogHarness() {
    const [repeatFiles, setRepeatFiles] = useState([
        { id: 1, remark: "morning_report.md 已存在" },
    ]);

    return (
        <DialogWithRepeatFiles
            repeatFiles={repeatFiles}
            retryLoad={false}
            t={(key: keyof typeof translations) => translations[key]}
            unRetry={() => setRepeatFiles([])}
            onRetry={() => setRepeatFiles([])}
        />
    );
}

describe("DuplicateFileDialog", () => {
    it("requires choosing an action instead of dismissing from outside or Escape", () => {
        render(<DialogHarness />);

        const dialog = screen.getByRole("dialog");
        const overlay = dialog.previousElementSibling;
        expect(overlay).not.toBeNull();

        fireEvent.pointerDown(overlay as Element);
        fireEvent.keyDown(document, { key: "Escape" });

        expect(screen.getByRole("dialog")).toBeInTheDocument();
    });

    it.each(["不覆盖，保留原文件", "覆盖"])("closes after choosing %s", async (buttonName) => {
        const user = userEvent.setup();
        render(<DialogHarness />);

        await user.click(screen.getByRole("button", { name: buttonName }));

        expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
});
