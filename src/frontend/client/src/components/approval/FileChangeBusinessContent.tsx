import type {
  ApprovalInstanceDetail,
  ApprovalTaskDetail,
} from "~/api/approval";
import { useLocalize } from "~/hooks";

import { FILE_CHANGE_SCENARIO_CODE } from "./approvalCenterFileChangeUtils";

interface FileChangeBusinessContentProps {
  detail: ApprovalTaskDetail | ApprovalInstanceDetail;
  localize: ReturnType<typeof useLocalize>;
}

interface BusinessContentRow {
  label: string;
  value: string;
}

const ACTION_KEYS = {
  delete: "com_knowledge.file_change_action_delete",
  move: "com_knowledge.file_change_action_move",
  rename: "com_knowledge.file_change_action_rename",
  upload: "com_knowledge.file_change_action_upload",
} as const;

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function readableString(...values: unknown[]): string | undefined {
  return values
    .find(
      (value): value is string =>
        typeof value === "string" && Boolean(value.trim()),
    )
    ?.trim();
}

function resourceNameFromTitle(
  value: string | null | undefined,
): string | undefined {
  if (!value) return undefined;
  return value.split(" / ").at(-1)?.trim() || undefined;
}

function localizedAction(
  action: unknown,
  localize: ReturnType<typeof useLocalize>,
): string {
  if (typeof action !== "string" || !(action in ACTION_KEYS)) return "--";
  return localize(ACTION_KEYS[action as keyof typeof ACTION_KEYS]);
}

export function buildFileChangeBusinessRows(
  detail: ApprovalTaskDetail | ApprovalInstanceDetail,
  localize: ReturnType<typeof useLocalize>,
): BusinessContentRow[] | null {
  if (detail.scenario_code !== FILE_CHANGE_SCENARIO_CODE) return null;

  const detailSnapshot = asRecord(detail.detail_snapshot);
  const payloadSnapshot = asRecord(detail.payload_snapshot);
  const change = asRecord(detailSnapshot.change);
  const action = readableString(detailSnapshot.action, payloadSnapshot.action);
  const resourceName =
    readableString(detailSnapshot.resource_name, change.resource_name) ??
    resourceNameFromTitle(detail.business_name) ??
    "--";
  const relativePath = readableString(
    change.relative_path,
    detailSnapshot.relative_path,
  );
  const targetPath = readableString(
    change.target_path,
    detailSnapshot.target_path,
    relativePath !== resourceName ? relativePath : undefined,
  );

  const rows: Array<BusinessContentRow | null> = [
    {
      label: localize("com_knowledge.file_change_action"),
      value: localizedAction(action, localize),
    },
    {
      label: localize("com_knowledge.file_name"),
      value: resourceName,
    },
    readableString(detailSnapshot.space_name, change.space_name)
      ? {
          label: localize("com_approval_field_space_name"),
          value: readableString(
            detailSnapshot.space_name,
            change.space_name,
          ) as string,
        }
      : null,
    readableString(change.old_name, detailSnapshot.old_name)
      ? {
          label: localize("com_knowledge.file_change_old_name"),
          value: readableString(
            change.old_name,
            detailSnapshot.old_name,
          ) as string,
        }
      : null,
    readableString(change.new_name, detailSnapshot.new_name)
      ? {
          label: localize("com_knowledge.file_change_new_name"),
          value: readableString(
            change.new_name,
            detailSnapshot.new_name,
          ) as string,
        }
      : null,
    readableString(change.source_path, detailSnapshot.source_path)
      ? {
          label: localize("com_knowledge.file_change_source_path"),
          value: readableString(
            change.source_path,
            detailSnapshot.source_path,
          ) as string,
        }
      : null,
    targetPath
      ? {
          label: localize("com_knowledge.file_change_target_path"),
          value: targetPath,
        }
      : null,
  ];

  return rows.filter((row): row is BusinessContentRow => row !== null);
}

export function FileChangeBusinessContent({
  detail,
  localize,
}: FileChangeBusinessContentProps) {
  const rows = buildFileChangeBusinessRows(detail, localize);
  if (!rows) return null;

  return (
    <div>
      <div className="mb-2 text-[14px] font-medium text-text-primary">
        {localize("com_approval_section_business_content")}
      </div>
      <div className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-[#f2f3f5] bg-[#f2f3f5]">
        {rows.map((row) => (
          <div key={row.label} className="bg-white px-3 py-2">
            <div className="text-[12px] text-[#86909c]">{row.label}</div>
            <div className="mt-1 break-all text-[14px] text-text-primary">
              {row.value}
            </div>
          </div>
        ))}
        {rows.length % 2 === 1 && <div className="-ml-px bg-white" />}
      </div>
    </div>
  );
}
