import { splitEditableFileName, joinEditableFileName } from "./useInlineRename";

describe("splitEditableFileName", () => {
  test("splits base and extension for a normal file", () => {
    expect(splitEditableFileName("report.pdf", false)).toEqual({ base: "report", ext: ".pdf" });
  });

  test("uses the last dot for multi-dot names", () => {
    expect(splitEditableFileName("2026.report.final.docx", false)).toEqual({
      base: "2026.report.final",
      ext: ".docx",
    });
  });

  test("no extension when the name has no dot", () => {
    expect(splitEditableFileName("readme", false)).toEqual({ base: "readme", ext: "" });
  });

  test("no extension for a dotfile (leading dot only)", () => {
    expect(splitEditableFileName(".gitignore", false)).toEqual({ base: ".gitignore", ext: "" });
  });

  test("folders keep the whole name editable, no extension", () => {
    expect(splitEditableFileName("my.folder", true)).toEqual({ base: "my.folder", ext: "" });
  });
});

describe("joinEditableFileName", () => {
  test("re-appends the extension and trims the base", () => {
    expect(joinEditableFileName("  report ", ".pdf")).toBe("report.pdf");
  });

  test("returns base unchanged when there is no extension", () => {
    expect(joinEditableFileName("readme", "")).toBe("readme");
  });
});
