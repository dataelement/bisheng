import { describe, expect, it } from "vitest";
import {
  initialWizardStrategy,
  wizardOverrides,
} from "@/pages/KnowledgePage/components/uploadWizardRules";
import { uploadDefaults } from "./uploadWizardFixtures";
const file = (id: string, table = false) => ({
  id,
  fileName: `${id}.${table ? "csv" : "md"}`,
  file_path: `tmp/${id}`,
  suffix: table ? "csv" : "md",
  fileType: table ? ("table" as const) : ("file" as const),
  split_rule: {},
});
describe("legacy upload rule adapter", () => {
  it("preserves zero/false system defaults and the empty auto separator", () => {
    const before = structuredClone(uploadDefaults);
    const value = initialWizardStrategy(uploadDefaults, 7, [file("doc")]);
    expect(wizardOverrides(value, "tmp/doc")).toEqual({
      document: uploadDefaults.document,
      table: uploadDefaults.table,
    });
    expect(uploadDefaults).toEqual(before);
  });
  it("uses each table's selected rule without changing another table", () => {
    const value = initialWizardStrategy(uploadDefaults, 7, [
      file("a", true),
      file("b", true),
      file("doc"),
    ]);
    value.applyEachCell = true;
    value.rules.fileList[0].excelRule.slice_length = "22";
    expect(wizardOverrides(value, "tmp/a").table?.slice_length).toBe(22);
    expect(wizardOverrides(value, "tmp/b").table?.slice_length).toBe(10);
    expect(wizardOverrides(value, "tmp/doc").table?.slice_length).toBe(10);
  });
  it("rejects incomplete numeric input instead of silently submitting defaults", () => {
    const value = initialWizardStrategy(uploadDefaults, 7, [file("doc")]);
    value.rules.chunkSize = "";
    expect(() => wizardOverrides(value, "tmp/doc")).toThrow();
  });
  it("converts legacy newline editing into parser rules and numeric flags", () => {
    const value = initialWizardStrategy(uploadDefaults, 7, [file("doc")]);
    value.rules.separator = ["\\n\\n"];
    value.rules.retainImages = true;
    value.cellGeneralConfig.append_header = false;
    expect(wizardOverrides(value, "tmp/doc").document).toMatchObject({
      separator: ["\n\n"],
      retain_images: 1,
    });
    expect(wizardOverrides(value, "tmp/doc").table?.append_header).toBe(0);
  });
});
