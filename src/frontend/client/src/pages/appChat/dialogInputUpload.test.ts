import { getDialogInputUploadSettings } from "./dialogInputUpload";

describe("dialog input upload settings", () => {
    it("hides upload when user_input_file is false", () => {
        expect(
            getDialogInputUploadSettings({
                tab: "dialog_input",
                value: [
                    { key: "dialog_file_accept", value: "file" },
                    { key: "user_input_file", value: false },
                ],
            }),
        ).toEqual({
            fileAccept: "file",
            showUpload: false,
        });
    });

    it("hides upload when user_input_file is string false", () => {
        expect(
            getDialogInputUploadSettings({
                tab: "dialog_input",
                value: [
                    { key: "dialog_file_accept", value: "image" },
                    { key: "user_input_file", value: "false" },
                ],
            }),
        ).toEqual({
            fileAccept: "image",
            showUpload: false,
        });
    });

    it("shows upload by default for dialog input nodes", () => {
        expect(
            getDialogInputUploadSettings({
                tab: "dialog_input",
                value: [{ key: "dialog_file_accept", value: "all" }],
            }),
        ).toEqual({
            fileAccept: "all",
            showUpload: true,
        });
    });

    it("does not show upload for non-dialog input schemas", () => {
        expect(getDialogInputUploadSettings({ tab: "runtime_knowledge", value: [] })).toEqual({
            fileAccept: undefined,
            showUpload: false,
        });
    });
});
