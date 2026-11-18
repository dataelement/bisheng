import { expect, it } from "vitest";
import type { ProcessingDefaults } from "@/controllers/API/knowledgeSpace";
import {
  fileProcessingDefaults,
  fileProcessingOverrides,
  fileRuleScope,
} from "@/pages/KnowledgePage/components/fileProcessingRules";

const defaults: ProcessingDefaults = {
  schema_version: 1,
  document: {
    split_mode: "auto",
    separator: ["\n", ""],
    separator_rule: ["after", "after"],
    chunk_size: 1000,
    chunk_overlap: 100,
    hierarchy_level: 3,
    append_title: false,
    max_chunk_size: 1000,
    retain_images: 1,
    force_ocr: 1,
    enable_formula: 0,
    filter_page_header_footer: 0,
  },
  table: {
    slice_length: 10,
    header_start_row: 1,
    header_end_row: 1,
    append_header: 1,
  },
};
it.each(["mp3", "wav", "mp4", "mov"])(
  "does not submit unused document/table rules for %s",
  (suffix) => {
    const file = { file_name: `clip.${suffix}` };
    expect(fileRuleScope(file)).toBe("specialized");
    expect(fileProcessingOverrides(defaults, file)).toEqual({});
  },
);
it("keeps web rules dedicated even when its display name ends in a document extension", () => {
  expect(
    fileProcessingOverrides(defaults, {
      file_name: "site.md",
      file_source: "web_link",
    }),
  ).toEqual({});
});
it("sends only table fields for a spreadsheet and only applicable document fields for a text file", () => {
  expect(
    fileProcessingOverrides(defaults, { file_name: "table.xlsx" }),
  ).toEqual({ table: defaults.table });
  const text = fileProcessingOverrides(defaults, { file_name: "text.txt" });
  expect(text.table).toBeUndefined();
  expect(text.document).not.toHaveProperty("force_ocr");
  expect(
    fileProcessingOverrides(defaults, { file_name: "scan.pdf" }).document
      ?.force_ocr,
  ).toBe(1);
});
it("echoes the file's own settings without inheriting its unused legacy table rules", () => {
  const before = structuredClone(defaults);
  const value = fileProcessingDefaults(defaults, {
    file_name: "text.txt",
    split_rule: JSON.stringify({
      chunk_size: 222,
      split_mode: "hierarchical",
      excel_rule: { slice_length: 0 },
    }),
  });
  expect(value.document.chunk_size).toBe(222);
  expect(value.document.split_mode).toBe("auto");
  expect(value.table).toEqual(defaults.table);
  expect(defaults).toEqual(before);
});
it("uses the web splitter's forced separators and zero overlap in its preview", () => {
  const value = fileProcessingDefaults(defaults, {
    file_name: "site.md",
    file_source: "web_link",
  });
  expect(value.document.chunk_overlap).toBe(0);
  expect(value.document.separator).toEqual(["\n\n", "\n", "。", "\\.", "，", ",", "；", ";", "、", "\\s+", ""]);
  expect(value.document.separator_rule).toHaveLength(
    value.document.separator.length,
  );
});
