import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, expect, it, vi } from "vitest";
import type { ProcessingDefaults } from "@/controllers/API/knowledgeSpace";
import { ProcessingDefaultsEditor, processingDefaultsToDraft, validateProcessingDefaultsDraft, type ProcessingDefaultsDraft } from "@/pages/KnowledgePage/components/ProcessingDefaultsEditor";

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (key: string) => key, i18n: { resolvedLanguage: "en" } }) }));
afterEach(cleanup);
const defaults: ProcessingDefaults = {
  schema_version: 1,
  document: { split_mode: "custom", separator: ["\\n", "\n", ""], separator_rule: ["before", "after", "after"], chunk_size: 300, chunk_overlap: 20, hierarchy_level: 6, append_title: false, max_chunk_size: 600, retain_images: 1, force_ocr: 1, enable_formula: 0, filter_page_header_footer: 1 },
  table: { slice_length: 10, header_start_row: 1, header_end_row: 2, append_header: 0 },
};
function Harness() {
  const [value, onChange] = useState(() => processingDefaultsToDraft(defaults));
  return <><ProcessingDefaultsEditor value={value} onChange={onChange} /><output data-testid="draft">{JSON.stringify(value)}</output></>;
}
const draft = (): ProcessingDefaultsDraft => JSON.parse(screen.getByTestId("draft").textContent || "{}");
const type = (key: string) => fireEvent.mouseDown(screen.getByRole("tab", { name: `f118.${key}` }), { button: 0, ctrlKey: false });

it("projects every actual rule field without UI fields or token normalization", () => {
  const value = processingDefaultsToDraft(defaults);
  expect(validateProcessingDefaultsDraft(value)).toEqual({ ok: true, value: defaults });
  value.document.separator[0] = "changed";
  expect(defaults.document.separator[0]).toBe("\\n");
  expect(value.table).not.toBe(defaults.table);
});

it.each([
  (value: ProcessingDefaultsDraft) => { value.document.chunk_size = null; },
  (value: ProcessingDefaultsDraft) => { value.document.max_chunk_size = 0; },
  (value: ProcessingDefaultsDraft) => { value.document.hierarchy_level = 7; },
  (value: ProcessingDefaultsDraft) => { value.document.hierarchy_level = 1.5; },
  (value: ProcessingDefaultsDraft) => { value.document.chunk_overlap = 301; value.document.split_mode = "auto"; },
  (value: ProcessingDefaultsDraft) => { value.table.slice_length = Number.POSITIVE_INFINITY; },
  (value: ProcessingDefaultsDraft) => { value.table.slice_length = Number.MAX_SAFE_INTEGER + 1; },
  (value: ProcessingDefaultsDraft) => { value.table.header_start_row = 3; },
  (value: ProcessingDefaultsDraft) => { value.document.separator = []; value.document.separator_rule = []; },
  (value: ProcessingDefaultsDraft) => { value.document.separator_rule = ["after"]; },
])("validates the full draft including inactive types and modes", change => {
  const value = processingDefaultsToDraft(defaults);
  change(value);
  const before = JSON.stringify(value);
  expect(validateProcessingDefaultsDraft(value)).toMatchObject({ ok: false, reason: "invalid_defaults" });
  expect(JSON.stringify(value)).toBe(before);
});

it("keeps both number drafts and unadded literal input across type switches", () => {
  render(<Harness />);
  fireEvent.change(screen.getByRole("spinbutton", { name: "splitLength" }), { target: { value: "" } });
  fireEvent.change(screen.getByRole("textbox", { name: "addCustomRule" }), { target: { value: " (?<=prefix) " } });
  type("tables");
  fireEvent.change(screen.getByRole("spinbutton", { name: "maxRowsPerSegment" }), { target: { value: "23" } });
  type("documents");
  expect(screen.getByRole("spinbutton", { name: "splitLength" })).toHaveValue("");
  expect(screen.getByRole("textbox", { name: "addCustomRule" })).toHaveValue(" (?<=prefix) ");
  expect(draft().table.slice_length).toBe(23);
  expect(validateProcessingDefaultsDraft(draft())).toMatchObject({ ok: false });
  expect(defaults.table.slice_length).toBe(10);
});

it("requires unadded input to be added or cleared and preserves rule ordering and empty fallback", () => {
  render(<Harness />);
  fireEvent.change(screen.getByRole("textbox", { name: "addCustomRule" }), { target: { value: " (?<=prefix) " } });
  expect(validateProcessingDefaultsDraft(draft())).toMatchObject({ ok: false, reason: "pending_separator" });
  fireEvent.click(screen.getByRole("button", { name: "add" }));
  expect(draft().document.separator).toEqual(["\\n", "\n", "", " (?<=prefix) "]);
  fireEvent.click(screen.getAllByRole("button", { name: "f118.move_down" })[0]);
  expect(draft().document.separator.slice(0, 2)).toEqual(["\n", "\\n"]);
  expect(draft().document.separator_rule.slice(0, 2)).toEqual(["after", "before"]);
  const result = validateProcessingDefaultsDraft(draft());
  expect(result.ok).toBe(true);
  if (result.ok) {
    expect(Object.keys(result.value)).toEqual(["schema_version", "document", "table"]);
    expect(result.value.document.separator[2]).toBe("");
    expect(JSON.stringify(result.value)).not.toContain("pendingPattern");
  }
});
