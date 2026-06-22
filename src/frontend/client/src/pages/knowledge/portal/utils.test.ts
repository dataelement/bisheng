import { extractExt } from "./utils";

describe("portal preview utils", () => {
    describe("extractExt", () => {
        it("prefers the preview URL extension for web link titles without an extension", () => {
            expect(
                extractExt(
                    "首钢股份知库 – 钢铁行业知识共享平台",
                    "http://localhost:9000/bisheng/preview/74.md?X-Amz-Signature=abc",
                ),
            ).toBe("md");
        });

        it("uses the preview URL extension for media transcript previews", () => {
            expect(
                extractExt(
                    "乔布斯_副本.m4a",
                    "http://localhost:9000/bisheng/preview/88.md",
                ),
            ).toBe("md");
        });

        it("does not treat an extensionless display name as a file type", () => {
            expect(extractExt("首钢股份知库 – 钢铁行业知识共享平台")).toBe("txt");
        });

        it("falls back to the display name extension when no preview URL is available", () => {
            expect(extractExt("VCU告警操作文档.docx")).toBe("docx");
        });
    });
});
