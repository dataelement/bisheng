import { useCallback, useMemo, useReducer } from "react";
import type { PermissionGrantMutationChange, SubjectType } from "~/api/permission";

export interface PermissionDraftRow {
  subjectType: SubjectType;
  subjectId: number;
  subjectName: string;
  modelKey: string;
  modelName?: string;
  modelLevel?: number | null;
  includeChildren?: boolean;
  assigneeId?: string;
  assigneeVersion?: number;
  sourceType?: string;
  scope?: "LOCAL" | "INHERITED";
  inheritedFrom?: string | null;
  protected?: boolean;
  editable?: boolean;
}

export interface PermissionDraftBaseline {
  resourceVersion: number;
  catalogReleaseId: number;
}

export interface PermissionDraft {
  baseline: PermissionDraftRow[];
  rows: PermissionDraftRow[];
  touchedAssigneeIds: string[];
  baselineVersion?: PermissionDraftBaseline;
}

export interface PermissionDraftDiff {
  changes: PermissionGrantMutationChange[];
}

export type PermissionDraftAction =
  | { type: "add"; row: PermissionDraftRow }
  | { type: "change"; key: string; changes: Partial<PermissionDraftRow> }
  | { type: "remove"; key: string }
  | { type: "replace_rows"; rows: PermissionDraftRow[]; baselineVersion?: PermissionDraftBaseline }
  | { type: "reset"; rows?: PermissionDraftRow[]; baselineVersion?: PermissionDraftBaseline };

const EMPTY_DIFF: PermissionDraftDiff = { changes: [] };

function cloneRows(rows: PermissionDraftRow[]): PermissionDraftRow[] {
  return rows.map((row) => ({ ...row }));
}

function isReadOnly(row: PermissionDraftRow): boolean {
  return row.protected === true || row.scope === "INHERITED" || row.editable === false;
}

export function getPermissionDraftRowKey(row: PermissionDraftRow): string {
  return row.assigneeId ?? JSON.stringify([
    row.subjectType,
    row.subjectId,
    row.modelKey,
    row.includeChildren ?? null,
  ]);
}

function uniqueRows(rows: PermissionDraftRow[]): PermissionDraftRow[] {
  const seen = new Set<string>();
  return rows.filter((row) => {
    const key = getPermissionDraftRowKey(row);
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

export function createPermissionDraft(
  rows: PermissionDraftRow[] = [],
  baselineVersion?: PermissionDraftBaseline,
): PermissionDraft {
  const baseline = uniqueRows(cloneRows(rows));
  return { baseline, rows: cloneRows(baseline), touchedAssigneeIds: [], baselineVersion };
}

function touch(state: PermissionDraft, row: PermissionDraftRow): string[] {
  const key = getPermissionDraftRowKey(row);
  return state.touchedAssigneeIds.includes(key)
    ? state.touchedAssigneeIds
    : [...state.touchedAssigneeIds, key];
}

export function permissionDraftReducer(
  state: PermissionDraft,
  action: PermissionDraftAction,
): PermissionDraft {
  if (action.type === "reset") {
    return createPermissionDraft(
      action.rows ?? state.baseline,
      action.baselineVersion ?? state.baselineVersion,
    );
  }
  if (action.type === "replace_rows") {
    return createPermissionDraft(action.rows, action.baselineVersion);
  }
  if (action.type === "add") {
    if (isReadOnly(action.row)) return state;
    const key = getPermissionDraftRowKey(action.row);
    if (state.rows.some((row) => getPermissionDraftRowKey(row) === key)) return state;
    return {
      ...state,
      rows: [...state.rows, { ...action.row }],
      touchedAssigneeIds: touch(state, action.row),
    };
  }
  const index = state.rows.findIndex((row) => getPermissionDraftRowKey(row) === action.key);
  if (index < 0 || isReadOnly(state.rows[index])) return state;
  const previous = state.rows[index];
  if (action.type === "remove") {
    return {
      ...state,
      rows: state.rows.filter((_, rowIndex) => rowIndex !== index),
      touchedAssigneeIds: touch(state, previous),
    };
  }
  const next = { ...previous, ...action.changes };
  if (next.modelKey === previous.modelKey) return state;
  const rows = state.rows.slice();
  rows[index] = next;
  return { ...state, rows, touchedAssigneeIds: touch(state, previous) };
}

export function getPermissionDraftDiff(draft: PermissionDraft): PermissionDraftDiff {
  if (draft.touchedAssigneeIds.length === 0) return EMPTY_DIFF;
  const baselineByKey = new Map(draft.baseline.map((row) => [getPermissionDraftRowKey(row), row]));
  const rowsByKey = new Map(draft.rows.map((row) => [getPermissionDraftRowKey(row), row]));
  const changes: PermissionGrantMutationChange[] = [];
  for (const key of draft.touchedAssigneeIds) {
    const baseline = baselineByKey.get(key);
    const current = rowsByKey.get(key);
    if (!baseline && current) {
      changes.push({
        op: "ADD",
        model_key: current.modelKey,
        subject: {
          type: current.subjectType,
          id: String(current.subjectId),
          ...(current.subjectType === "department"
            ? {
                userset_relation: current.includeChildren ? "subtree_member" : null,
                include_children: Boolean(current.includeChildren),
              }
            : {}),
        },
      });
    } else if (baseline && !current && baseline.assigneeId != null && baseline.assigneeVersion != null) {
      changes.push({
        op: "REMOVE",
        assignee_id: baseline.assigneeId,
        expected_assignee_version: baseline.assigneeVersion,
      });
    } else if (
      baseline && current && baseline.modelKey !== current.modelKey
      && baseline.assigneeId != null && baseline.assigneeVersion != null
    ) {
      changes.push({
        op: "MOVE",
        assignee_id: baseline.assigneeId,
        expected_assignee_version: baseline.assigneeVersion,
        target_model_key: current.modelKey,
      });
    }
  }
  return { changes };
}

export function usePermissionDraft(initialRows: PermissionDraftRow[] = []) {
  const [draft, dispatch] = useReducer(permissionDraftReducer, initialRows, createPermissionDraft);
  const diff = useMemo(() => getPermissionDraftDiff(draft), [draft]);
  const addRow = useCallback((row: PermissionDraftRow) => dispatch({ type: "add", row }), []);
  const addRows = useCallback((rows: PermissionDraftRow[]) => {
    rows.forEach((row) => dispatch({ type: "add", row }));
  }, []);
  const changeRow = useCallback((key: string, changes: Partial<PermissionDraftRow>) => {
    dispatch({ type: "change", key, changes });
  }, []);
  const removeRow = useCallback((key: string) => dispatch({ type: "remove", key }), []);
  const replaceRows = useCallback((rows: PermissionDraftRow[], baselineVersion?: PermissionDraftBaseline) => {
    dispatch({ type: "replace_rows", rows, baselineVersion });
  }, []);
  const reset = useCallback((rows?: PermissionDraftRow[], baselineVersion?: PermissionDraftBaseline) => {
    dispatch({ type: "reset", rows, baselineVersion });
  }, []);
  const cancel = useCallback(() => dispatch({ type: "reset" }), []);
  return {
    draft,
    rows: draft.rows,
    diff,
    hasChanges: diff.changes.length > 0,
    addRow,
    addRows,
    changeRow,
    updateRow: changeRow,
    removeRow,
    replaceRows,
    reset,
    cancel,
  };
}
