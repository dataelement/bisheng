import type {
  ProcessingDefaults,
  ProcessingOverrides,
  TableProcessingRule,
} from "@/controllers/API/knowledgeSpace";
import {
  processingDefaultsToDraft,
  validateProcessingDefaultsDraft,
} from "./ProcessingDefaultsEditor";

type NumberInput = number | string;
interface TableInputs {
  slice_length: NumberInput;
  header_start_row: NumberInput;
  header_end_row: NumberInput;
  append_header: boolean | number;
}
export interface WizardFile {
  id: string;
  fileName: string;
  file_path: string;
  suffix: string;
  fileType: "table" | "file";
  split_rule: object;
}
export interface WizardRules {
  knowledgeId: number;
  fileList: {
    id: string;
    fileName: string;
    filePath: string;
    suffix: string;
    fileType: "table" | "file";
    excelRule: TableInputs;
  }[];
  separator: string[];
  separatorRule: ("before" | "after")[];
  chunkSize: NumberInput;
  chunkOverlap: NumberInput;
  hierarchyLevel: NumberInput;
  maxChunkSize: NumberInput;
  splitMode: "auto" | "custom" | "hierarchical";
  appendTitle: boolean;
  retainImages: boolean | number;
  enableFormula: boolean | number;
  forceOcr: boolean | number;
  pageHeaderFooter: boolean | number;
}
export interface WizardStrategy {
  rules: WizardRules;
  applyEachCell: boolean;
  cellGeneralConfig: TableInputs;
  strategies: {
    id: string;
    regex: string;
    position: "before" | "after";
    rule: string;
  }[];
}
const flag = (value: boolean | number): 0 | 1 =>
  value === true || value === 1 ? 1 : 0;
const tableRule = (value: TableInputs): TableProcessingRule => ({
  slice_length: Number(value.slice_length),
  header_start_row: Number(value.header_start_row),
  header_end_row: Number(value.header_end_row),
  append_header: flag(value.append_header),
});
export function initialWizardStrategy(
  defaults: ProcessingDefaults,
  spaceId: number,
  files: WizardFile[],
): WizardStrategy {
  const d = defaults.document;
  return {
    rules: {
      knowledgeId: spaceId,
      fileList: files.map((file) => ({
        id: file.id,
        fileName: file.fileName,
        filePath: file.file_path,
        suffix: file.suffix,
        fileType: file.fileType,
        excelRule: { ...defaults.table },
      })),
      separator: d.separator.slice(),
      separatorRule: d.separator_rule.slice(),
      chunkSize: d.chunk_size,
      chunkOverlap: d.chunk_overlap,
      hierarchyLevel: d.hierarchy_level,
      maxChunkSize: d.max_chunk_size,
      splitMode: d.split_mode,
      appendTitle: d.append_title,
      retainImages: d.retain_images,
      enableFormula: d.enable_formula,
      forceOcr: d.force_ocr,
      pageHeaderFooter: d.filter_page_header_footer,
    },
    applyEachCell: false,
    cellGeneralConfig: { ...defaults.table },
    strategies: d.separator.map((regex, i) => ({
      id: String(i),
      regex: regex.replace(/\n/g, "\\n"),
      position: d.separator_rule[i],
      rule: "",
    })),
  };
}
export function wizardOverrides(
  strategy: WizardStrategy,
  path: string,
): ProcessingOverrides {
  const r = strategy.rules;
  const file = r.fileList.find((item) => item.filePath === path);
  const table =
    strategy.applyEachCell && file?.fileType === "table"
      ? file.excelRule
      : strategy.cellGeneralConfig;
  if (!table) throw new Error("Missing file rule");
  const value: ProcessingDefaults = {
    schema_version: 1,
    document: {
      split_mode: r.splitMode,
      separator: r.separator.map((s) => s.replace(/\\n/g, "\n")),
      separator_rule: r.separatorRule,
      chunk_size: Number(r.chunkSize),
      chunk_overlap: Number(r.chunkOverlap),
      hierarchy_level: Number(r.hierarchyLevel),
      max_chunk_size: Number(r.maxChunkSize),
      append_title: Boolean(r.appendTitle),
      retain_images: flag(r.retainImages),
      force_ocr: flag(r.forceOcr),
      enable_formula: flag(r.enableFormula),
      filter_page_header_footer: flag(r.pageHeaderFooter),
    },
    table: tableRule(table),
  };
  const result = validateProcessingDefaultsDraft(
    processingDefaultsToDraft(value),
  );
  if (!result.ok) throw new Error("Invalid upload rules");
  return { document: result.value.document, table: result.value.table };
}
