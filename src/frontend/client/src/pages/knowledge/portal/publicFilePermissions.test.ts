import { buildPublicFileActionPermissions } from "./publicFilePermissions";

describe("buildPublicFileActionPermissions", () => {
    test("maps public folder permissions into every folder operation set", () => {
        const result = buildPublicFileActionPermissions({
            "101": [
                "rename_folder",
                "download_folder",
                "delete_folder",
                "move_folder",
                "manage_folder_relation",
            ],
        });

        expect(result.renameEntryIds).toEqual(new Set(["101"]));
        expect(result.downloadEntryIds).toEqual(new Set(["101"]));
        expect(result.deleteEntryIds).toEqual(new Set(["101"]));
        expect(result.moveEntryIds).toEqual(new Set(["101"]));
        expect(result.permissionEntryIds).toEqual(new Set(["101"]));
    });

    test("grants every public entry action to system administrators", () => {
        const result = buildPublicFileActionPermissions({}, ["101", "201"]);

        expect(result.renameEntryIds).toEqual(new Set(["101", "201"]));
        expect(result.downloadEntryIds).toEqual(new Set(["101", "201"]));
        expect(result.deleteEntryIds).toEqual(new Set(["101", "201"]));
        expect(result.moveEntryIds).toEqual(new Set(["101", "201"]));
        expect(result.permissionEntryIds).toEqual(new Set(["101", "201"]));
    });
});
