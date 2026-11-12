import { Button, Input, Select, Tabs } from "@bisheng/ui";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useSelectLabels } from "@/components/bs-comp/formFields/useSelectLabels";
import type {
  ProcessingDefaults,
  SeparatorRule,
} from "@/controllers/API/knowledgeSpace";
import {
  DocumentProcessingDefaultsFields,
  type DocumentProcessingDefaultsDraft,
} from "./RuleFile";
import {
  TableProcessingDefaultsFields,
  type TableProcessingDefaultsDraft,
} from "./RuleTable";

export interface ProcessingDefaultsDraft {
  schema_version: 1;
  document: DocumentProcessingDefaultsDraft;
  table: TableProcessingDefaultsDraft;
  pendingPattern: string;
  pendingPosition: SeparatorRule;
}
interface ProcessingDefaultsEditorProps {
  value: ProcessingDefaultsDraft;
  onChange: (value: ProcessingDefaultsDraft) => void;
  disabled?: boolean;
}
type DraftValidation =
  | { ok: true; value: ProcessingDefaults }
  | { ok: false; reason: "invalid_defaults" | "pending_separator" };

export function processingDefaultsToDraft(
  value: ProcessingDefaults,
): ProcessingDefaultsDraft {
  return {
    schema_version: 1,
    document: {
      ...value.document,
      separator: value.document.separator.slice(),
      separator_rule: value.document.separator_rule.slice(),
    },
    table: { ...value.table },
    pendingPattern: "",
    pendingPosition: "after",
  };
}
function integer(
  value: number | null,
  min: number,
  max = Number.MAX_SAFE_INTEGER,
): value is number {
  return (
    value !== null &&
    Number.isSafeInteger(value) &&
    value >= min &&
    value <= max
  );
}
export function validateProcessingDefaultsDraft(
  draft: ProcessingDefaultsDraft,
): DraftValidation {
  const d = draft.document,
    t = draft.table;
  if (draft.pendingPattern !== "")
    return { ok: false, reason: "pending_separator" };
  if (
    draft.schema_version !== 1 ||
    !["auto", "custom", "hierarchical"].includes(d.split_mode) ||
    !integer(d.chunk_size, 1) ||
    !integer(d.chunk_overlap, 0) ||
    d.chunk_overlap > d.chunk_size ||
    !integer(d.hierarchy_level, 1, 6) ||
    !integer(d.max_chunk_size, 1) ||
    !integer(t.slice_length, 1) ||
    !integer(t.header_start_row, 1) ||
    !integer(t.header_end_row, 1) ||
    t.header_start_row > t.header_end_row ||
    typeof d.append_title !== "boolean" ||
    ![
      d.retain_images,
      d.force_ocr,
      d.enable_formula,
      d.filter_page_header_footer,
      t.append_header,
    ].every((flag) => flag === 0 || flag === 1) ||
    !Array.isArray(d.separator) ||
    !d.separator.length ||
    !d.separator.every((token) => typeof token === "string") ||
    !Array.isArray(d.separator_rule) ||
    d.separator.length !== d.separator_rule.length ||
    !d.separator_rule.every(
      (position) => position === "before" || position === "after",
    )
  ) {
    return { ok: false, reason: "invalid_defaults" };
  }
  return {
    ok: true,
    value: {
      schema_version: 1,
      document: {
        split_mode: d.split_mode,
        separator: d.separator.slice(),
        separator_rule: d.separator_rule.slice(),
        chunk_size: d.chunk_size,
        chunk_overlap: d.chunk_overlap,
        hierarchy_level: d.hierarchy_level,
        append_title: d.append_title,
        max_chunk_size: d.max_chunk_size,
        retain_images: d.retain_images,
        force_ocr: d.force_ocr,
        enable_formula: d.enable_formula,
        filter_page_header_footer: d.filter_page_header_footer,
      },
      table: {
        slice_length: t.slice_length,
        header_start_row: t.header_start_row,
        header_end_row: t.header_end_row,
        append_header: t.append_header,
      },
    },
  };
}

/** UI-only pending input never enters the persisted rule. */
export function ProcessingDefaultsEditor({
  value,
  onChange,
  disabled = false,
}: ProcessingDefaultsEditorProps) {
  const { t } = useTranslation("knowledge");
  const selectLabels = useSelectLabels();
  const [active, setActive] = useState("documents");
  const document = value.document;
  const validation = validateProcessingDefaultsDraft(value);
  const positions = [
    { value: "before", label: t("before") },
    { value: "after", label: t("after") },
  ];
  const handleMove = (index: number, direction: number) => {
    const next = index + direction;
    if (next < 0 || next >= document.separator.length) return;
    const separator = document.separator.slice(),
      separator_rule = document.separator_rule.slice();
    [separator[index], separator[next]] = [separator[next], separator[index]];
    [separator_rule[index], separator_rule[next]] = [
      separator_rule[next],
      separator_rule[index],
    ];
    onChange({
      ...value,
      document: { ...document, separator, separator_rule },
    });
  };
  const documentPanel = (
    <div className="space-y-4">
      <DocumentProcessingDefaultsFields
        value={document}
        disabled={disabled}
        onChange={(next) => onChange({ ...value, document: next })}
      />
      <fieldset disabled={disabled} className="space-y-3 rounded-lg border p-4">
        <h3 className="text-sm font-medium">{t("addedRules")}</h3>
        {document.separator.map((pattern, index) => (
          <div key={index} className="flex flex-wrap items-center gap-2">
            <Input
              aria-label={t("f118.separator_pattern", { index: index + 1 })}
              value={pattern}
              disabled={disabled}
              onChange={(event) =>
                onChange({
                  ...value,
                  document: {
                    ...document,
                    separator: document.separator.map((token, i) =>
                      i === index ? event.target.value : token,
                    ),
                  },
                })
              }
            />
            <Select
              {...selectLabels}
              aria-label={t("f118.separator_position", { index: index + 1 })}
              value={document.separator_rule[index]}
              disabled={disabled}
              options={positions}
              onChange={(position) => {
                if (position === "before" || position === "after")
                  onChange({
                    ...value,
                    document: {
                      ...document,
                      separator_rule: document.separator_rule.map((old, i) =>
                        i === index ? position : old,
                      ),
                    },
                  });
              }}
            />
            <Button
              variant="outlined"
              color="default"
              disabled={disabled || index === 0}
              onClick={() => handleMove(index, -1)}
            >
              {t("f118.move_up")}
            </Button>
            <Button
              variant="outlined"
              color="default"
              disabled={disabled || index === document.separator.length - 1}
              onClick={() => handleMove(index, 1)}
            >
              {t("f118.move_down")}
            </Button>
            <Button
              variant="outlined"
              color="default"
              disabled={disabled}
              onClick={() =>
                onChange({
                  ...value,
                  document: {
                    ...document,
                    separator: document.separator.filter((_, i) => i !== index),
                    separator_rule: document.separator_rule.filter(
                      (_, i) => i !== index,
                    ),
                  },
                })
              }
            >
              {t("delete")}
            </Button>
          </div>
        ))}
        <div className="flex flex-wrap items-center gap-2">
          <Input
            aria-label={t("addCustomRule")}
            placeholder={t("enterRegex")}
            value={value.pendingPattern}
            disabled={disabled}
            onChange={(event) =>
              onChange({ ...value, pendingPattern: event.target.value })
            }
          />
          <Select
            {...selectLabels}
            aria-label={t("f118.separator_position", {
              index: document.separator.length + 1,
            })}
            disabled={disabled}
            options={positions}
            value={value.pendingPosition}
            onChange={(position) => {
              if (position === "before" || position === "after")
                onChange({ ...value, pendingPosition: position });
            }}
          />
          <Button
            variant="outlined"
            color="default"
            disabled={disabled || value.pendingPattern === ""}
            onClick={() =>
              onChange({
                ...value,
                pendingPattern: "",
                document: {
                  ...document,
                  separator: [...document.separator, value.pendingPattern],
                  separator_rule: [
                    ...document.separator_rule,
                    value.pendingPosition,
                  ],
                },
              })
            }
          >
            {t("add")}
          </Button>
        </div>
      </fieldset>
    </div>
  );
  return (
    <div className="space-y-4">
      <Tabs
        activeKey={active}
        onChange={setActive}
        items={[
          {
            key: "documents",
            label: t("f118.documents"),
            children: documentPanel,
          },
          {
            key: "tables",
            label: t("f118.tables"),
            children: (
              <TableProcessingDefaultsFields
                value={value.table}
                disabled={disabled}
                onChange={(table) => onChange({ ...value, table })}
              />
            ),
          },
        ]}
      />
      {!validation.ok && (
        <p role="alert" className="text-sm text-red-500">
          {t(`f118.${validation.reason}`)}
        </p>
      )}
    </div>
  );
}
