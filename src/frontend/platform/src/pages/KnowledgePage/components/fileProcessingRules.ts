import type { FileMetadata } from "@/controllers/API/knowledgeIndex";
import type {
  ProcessingDefaults,
  ProcessingOverrides,
} from "@/controllers/API/knowledgeSpace";

export type FileRuleScope = "document" | "table" | "specialized";
export function fileRuleScope(file: FileMetadata): FileRuleScope {
  const suffix = file.file_name?.split(".").pop()?.toLowerCase() ?? "";
  if (
    ["web_link", "audio_transcript", "video_transcript"].includes(
      file.file_source ?? "",
    ) ||
    [
      "mp3",
      "wav",
      "m4a",
      "aac",
      "flac",
      "ogg",
      "mp4",
      "mov",
      "avi",
      "mkv",
      "webm",
    ].includes(suffix)
  )
    return "specialized";
  return ["xls", "xlsx", "csv", "et"].includes(suffix) ? "table" : "document";
}
export function fileProcessingDefaults(
  defaults: ProcessingDefaults,
  file: FileMetadata,
): ProcessingDefaults {
  const rule: Record<string, unknown> =
    typeof file.split_rule === "string"
      ? JSON.parse(file.split_rule)
      : (file.split_rule ?? {});
  const document = { ...defaults.document };
  for (const key of Object.keys(document) as (keyof typeof document)[]) {
    if (key in rule) Object.assign(document, { [key]: rule[key] });
  }
  const scope = fileRuleScope(file);
  const suffix =
    file.file_source === "web_link"
      ? "md"
      : file.file_name?.split(".").pop()?.toLowerCase();
  if (
    document.split_mode === "hierarchical" &&
    !["md", "doc", "docx"].includes(suffix ?? "")
  )
    document.split_mode = "auto";
  if (file.file_source === "web_link") {
    document.separator = [
      "\n\n",
      "\n",
      "。",
      "\\.",
      "，",
      ",",
      "；",
      ";",
      "、",
      "\\s+",
      "",
    ];
    document.separator_rule = document.separator.map(() => "after");
    document.chunk_overlap = 0;
  }
  const table =
    scope === "table"
      ? {
          ...defaults.table,
          ...(rule.excel_rule as
            Partial<ProcessingDefaults["table"]> | undefined),
        }
      : { ...defaults.table };
  return {
    schema_version: 1,
    document: scope === "table" ? { ...defaults.document } : document,
    table,
  };
}
export function fileProcessingOverrides(
  value: ProcessingDefaults,
  file: FileMetadata,
): ProcessingOverrides {
  const scope = fileRuleScope(file);
  if (scope === "table") return { table: value.table };
  if (scope === "specialized") return {};
  const suffix = file.file_name?.split(".").pop()?.toLowerCase();
  const { force_ocr, enable_formula, filter_page_header_footer, ...document } =
    value.document;
  return {
    document: {
      ...document,
      split_mode:
        document.split_mode === "hierarchical" &&
        !["md", "doc", "docx"].includes(suffix ?? "")
          ? "auto"
          : document.split_mode,
      ...(suffix === "pdf"
        ? { force_ocr, enable_formula, filter_page_header_footer }
        : {}),
    },
  };
}
