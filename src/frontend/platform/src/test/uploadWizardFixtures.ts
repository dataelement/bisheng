import type { ProcessingDefaults } from "@/controllers/API/knowledgeSpace";
export const uploadDefaults: ProcessingDefaults = {
  schema_version: 1,
  document: {
    split_mode: "auto",
    separator: [""],
    separator_rule: ["after"],
    chunk_size: 300,
    chunk_overlap: 0,
    hierarchy_level: 3,
    max_chunk_size: 600,
    append_title: false,
    retain_images: 0,
    force_ocr: 0,
    enable_formula: 0,
    filter_page_header_footer: 0,
  },
  table: {
    slice_length: 10,
    append_header: 0,
    header_start_row: 1,
    header_end_row: 1,
  },
};
export const uploadSettings = () => ({
  space_id: 7,
  config_version: 4,
  saved_defaults: null,
  effective_defaults: structuredClone(uploadDefaults),
});
