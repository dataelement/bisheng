import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { cleanup } from "@testing-library/react";
import RuleFile from "@/pages/KnowledgePage/components/RuleFile";
import { DocumentProcessingDefaultsFields, type DocumentProcessingDefaultsDraft } from "@/pages/KnowledgePage/components/DocumentProcessingDefaultsFields";
import RuleTable, { TableProcessingDefaultsFields, type TableProcessingDefaultsDraft } from "@/pages/KnowledgePage/components/RuleTable";

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (key: string) => key, i18n: { resolvedLanguage: "en" } }) }));
vi.mock("@/pages/KnowledgePage/components/FileUploadSplitStrategy", () => ({ default: () => null }));
vi.mock("@/pages/KnowledgePage/components/KnowledgeTooltip", () => ({ KnowledgeHint: () => null, KnowledgeTooltip: ({ children }: { children: React.ReactNode }) => children }));
afterEach(cleanup);

const document: DocumentProcessingDefaultsDraft = {
  split_mode: "custom", separator: ["\\n", ""], separator_rule: ["before", "after"],
  chunk_size: 300, chunk_overlap: 20, hierarchy_level: 6, append_title: false, max_chunk_size: 600,
  retain_images: 1, force_ocr: 1, enable_formula: 0, filter_page_header_footer: 1,
};
const table: TableProcessingDefaultsDraft = { slice_length: 10, header_start_row: 1, header_end_row: 2, append_header: 0 };

function DocumentHarness({ disabled = false }: { disabled?: boolean }) {
  const [value, onChange] = useState(document);
  return <><DocumentProcessingDefaultsFields value={value} onChange={onChange} disabled={disabled} /><output data-testid="draft">{JSON.stringify(value)}</output></>;
}
function TableHarness() {
  const [value, onChange] = useState(table);
  return <><TableProcessingDefaultsFields value={value} onChange={onChange} /><output data-testid="draft">{JSON.stringify(value)}</output></>;
}
const draft = () => JSON.parse(screen.getByTestId("draft").textContent || "{}");

it("keeps a cleared document number null after blur and preserves all other actual fields", () => {
  render(<DocumentHarness />);
  const input = screen.getByRole("spinbutton", { name: "splitLength" });
  fireEvent.change(input, { target: { value: "" } });
  fireEvent.blur(input);
  expect(input).toHaveValue("");
  expect(draft()).toEqual({ ...document, chunk_size: null });
  fireEvent.change(input, { target: { value: "0" } });
  fireEvent.blur(input);
  expect(draft().chunk_size).toBe(0);
  expect(input).toHaveValue("0");
});

it("shows existing PDF options without a file list and writes exact binary flags", () => {
  render(<DocumentHarness />);
  expect(screen.getByText("pdfOptionsHint")).toBeVisible();
  fireEvent.click(screen.getByRole("checkbox", { name: "ocrForce" }));
  fireEvent.click(screen.getByRole("checkbox", { name: "enableRec" }));
  fireEvent.click(screen.getByRole("checkbox", { name: "hfFilter" }));
  fireEvent.click(screen.getByRole("checkbox", { name: "keepImages" }));
  expect(draft()).toMatchObject({ force_ocr: 0, enable_formula: 1, filter_page_header_footer: 0, retain_images: 0 });
});

it("accepts hierarchy six and preserves fractional/cleared drafts instead of coercing", () => {
  const onChange = vi.fn();
  const view = render(<DocumentProcessingDefaultsFields value={{ ...document, split_mode: "hierarchical" }} onChange={onChange} />);
  const hierarchy = screen.getByRole("spinbutton", { name: "splitLevel" });
  expect(hierarchy).toHaveValue("6");
  expect(hierarchy).toHaveAttribute("aria-valuemax", "6");
  fireEvent.change(hierarchy, { target: { value: "1.5" } });
  expect(onChange).toHaveBeenLastCalledWith({ ...document, split_mode: "hierarchical", hierarchy_level: 1.5 });
  view.rerender(<DocumentProcessingDefaultsFields value={{ ...document, split_mode: "hierarchical", hierarchy_level: null }} onChange={onChange} />);
  expect(hierarchy).toHaveValue("");
  fireEvent.click(screen.getByRole("checkbox", { name: "appendTitle" }));
  expect(onChange.mock.lastCall?.[0].append_title).toBe(true);
});

it("renders one table default without per-file inputs and preserves invalid header order", () => {
  render(<TableHarness />);
  expect(screen.queryByText("setSeparately")).toBeNull();
  const start = screen.getByRole("spinbutton", { name: "f118.header_start" });
  fireEvent.change(start, { target: { value: "8" } });
  expect(draft()).toEqual({ ...table, header_start_row: 8 });
  const rows = screen.getByRole("spinbutton", { name: "maxRowsPerSegment" });
  fireEvent.change(rows, { target: { value: "" } });
  fireEvent.blur(rows);
  expect(draft().slice_length).toBeNull();
  expect(rows).toHaveValue("");
  fireEvent.click(screen.getByRole("checkbox", { name: "addHeader" }));
  expect(draft().append_header).toBe(1);
});

it("disables default fields during an in-flight save", () => {
  render(<DocumentHarness disabled />);
  screen.getAllByRole("spinbutton").forEach(input => expect(input).toBeDisabled());
  screen.getAllByRole("checkbox").forEach(input => expect(input).toBeDisabled());
});

it("keeps the old upload components and their existing blur behavior", () => {
  const setRules = vi.fn(), setTable = vi.fn();
  const view = render(<RuleFile rules={{ splitMode: "custom", chunkSize: "300", chunkOverlap: "20" }} setRules={setRules} />);
  const input = screen.getByLabelText("splitLength");
  fireEvent.change(input, { target: { value: "" } });
  fireEvent.blur(input);
  expect(input).toHaveValue(1000);
  view.unmount();
  render(<RuleTable rules={{ fileList: [] }} setRules={vi.fn()} applyEachCell={false} setApplyEachCell={vi.fn()} cellGeneralConfig={table} setCellGeneralConfig={setTable} />);
  const oldRows = screen.getAllByRole("spinbutton")[0];
  fireEvent.change(oldRows, { target: { value: "" } });
  fireEvent.blur(oldRows);
  expect(setTable).toHaveBeenCalled();
});
