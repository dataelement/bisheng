import { useCallback, useMemo, useReducer } from "react";
import type {
  GrantItem,
  RelationLevel,
  RevokeItem,
  SubjectType,
} from "~/api/permission";

export interface PermissionDraftRow {
  subjectType: SubjectType;
  subjectId: number;
  subjectName: string;
  relation: RelationLevel;
  modelId?: string;
  includeChildren?: boolean;
  immutableCreator?: boolean;
  authorizationStatus?: "active" | "pending";
  approvalInstanceId?: number | null;
}

export interface PermissionDraft {
  baseline: PermissionDraftRow[];
  rows: PermissionDraftRow[];
  touchedKeys: string[];
}

export interface PermissionDraftDiff {
  grants: GrantItem[];
  revokes: RevokeItem[];
}

export type PermissionDraftAction =
  | { type: "add"; row: PermissionDraftRow }
  | { type: "change"; key: string; changes: Partial<PermissionDraftRow> }
  | { type: "remove"; key: string }
  | { type: "replace_rows"; rows: PermissionDraftRow[] }
  | { type: "reset"; rows?: PermissionDraftRow[] };

const EMPTY_DIFF: PermissionDraftDiff = { grants: [], revokes: [] };

function isImmutableRow(row: PermissionDraftRow): boolean {
  return row.immutableCreator === true || row.authorizationStatus === "pending";
}

function isSameSubject(left: PermissionDraftRow, right: PermissionDraftRow): boolean {
  return left.subjectType === right.subjectType && left.subjectId === right.subjectId;
}

function cloneRows(rows: PermissionDraftRow[]): PermissionDraftRow[] {
  return rows.map((row) => ({ ...row }));
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

function mergeTouchedKeys(current: string[], next: string[]): string[] {
  return Array.from(new Set([...current, ...next]));
}

function rowToGrant(row: PermissionDraftRow): GrantItem {
  return {
    subject_type: row.subjectType,
    subject_id: row.subjectId,
    relation: row.relation,
    ...(row.modelId ? { model_id: row.modelId } : {}),
    ...(row.includeChildren === undefined
      ? {}
      : { include_children: row.includeChildren }),
  };
}

function rowToRevoke(row: PermissionDraftRow): RevokeItem {
  return {
    subject_type: row.subjectType,
    subject_id: row.subjectId,
    relation: row.relation,
    ...(row.includeChildren === undefined
      ? {}
      : { include_children: row.includeChildren }),
  };
}

export function getPermissionDraftRowKey(row: PermissionDraftRow): string {
  return JSON.stringify([
    row.subjectType,
    row.subjectId,
    row.relation,
    row.modelId ?? "",
    row.includeChildren ?? null,
  ]);
}

export function createPermissionDraft(rows: PermissionDraftRow[] = []): PermissionDraft {
  const baseline = uniqueRows(cloneRows(rows));
  return {
    baseline,
    rows: cloneRows(baseline),
    touchedKeys: [],
  };
}

export function permissionDraftReducer(
  state: PermissionDraft,
  action: PermissionDraftAction,
): PermissionDraft {
  if (action.type === "reset") {
    return createPermissionDraft(action.rows ?? state.baseline);
  }

  if (action.type === "add") {
    const key = getPermissionDraftRowKey(action.row);
    if (state.rows.some((row) => getPermissionDraftRowKey(row) === key)) {
      return state;
    }
    return {
      ...state,
      rows: [...state.rows, { ...action.row }],
      touchedKeys: mergeTouchedKeys(state.touchedKeys, [key]),
    };
  }

  if (action.type === "change") {
    const index = state.rows.findIndex((row) => getPermissionDraftRowKey(row) === action.key);
    if (index < 0 || isImmutableRow(state.rows[index])) return state;

    const previous = state.rows[index];
    const next = {
      ...previous,
      ...action.changes,
      immutableCreator: previous.immutableCreator,
      authorizationStatus: previous.authorizationStatus,
      approvalInstanceId: previous.approvalInstanceId,
    };
    if (JSON.stringify(previous) === JSON.stringify(next)) return state;

    const rows = state.rows.slice();
    rows[index] = next;
    return {
      ...state,
      rows,
      touchedKeys: mergeTouchedKeys(state.touchedKeys, [
        getPermissionDraftRowKey(previous),
        getPermissionDraftRowKey(next),
      ]),
    };
  }

  if (action.type === "remove") {
    const row = state.rows.find((candidate) => getPermissionDraftRowKey(candidate) === action.key);
    if (!row || isImmutableRow(row)) return state;
    return {
      ...state,
      rows: state.rows.filter((candidate) => getPermissionDraftRowKey(candidate) !== action.key),
      touchedKeys: mergeTouchedKeys(state.touchedKeys, [action.key]),
    };
  }

  const immutableRows = state.rows.filter(isImmutableRow);
  const rows = uniqueRows([
    ...immutableRows,
    ...cloneRows(action.rows).filter(
      (row) => !immutableRows.some((immutableRow) => isSameSubject(immutableRow, row)),
    ),
  ]);
  const currentKeys = state.rows.map(getPermissionDraftRowKey);
  const nextKeys = rows.map(getPermissionDraftRowKey);
  const currentKeySet = new Set(currentKeys);
  const nextKeySet = new Set(nextKeys);
  const changedKeys = [
    ...currentKeys.filter((key) => !nextKeySet.has(key)),
    ...nextKeys.filter((key) => !currentKeySet.has(key)),
  ];
  if (changedKeys.length === 0) return state;

  return {
    ...state,
    rows,
    touchedKeys: mergeTouchedKeys(state.touchedKeys, changedKeys),
  };
}

export function getPermissionDraftDiff(draft: PermissionDraft): PermissionDraftDiff {
  if (draft.touchedKeys.length === 0) return EMPTY_DIFF;

  const touchedKeys = new Set(draft.touchedKeys);
  const baselineKeys = new Set(draft.baseline.map(getPermissionDraftRowKey));
  const rowKeys = new Set(draft.rows.map(getPermissionDraftRowKey));

  return {
    grants: draft.rows
      .filter((row) => {
        if (isImmutableRow(row)) return false;
        const key = getPermissionDraftRowKey(row);
        return touchedKeys.has(key) && !baselineKeys.has(key);
      })
      .map(rowToGrant),
    revokes: draft.baseline
      .filter((row) => {
        if (isImmutableRow(row)) return false;
        const key = getPermissionDraftRowKey(row);
        return touchedKeys.has(key) && !rowKeys.has(key);
      })
      .map(rowToRevoke),
  };
}

export function usePermissionDraft(initialRows: PermissionDraftRow[] = []) {
  const [draft, dispatch] = useReducer(
    permissionDraftReducer,
    initialRows,
    createPermissionDraft,
  );
  const diff = useMemo(() => getPermissionDraftDiff(draft), [draft]);

  const addRow = useCallback((row: PermissionDraftRow) => {
    dispatch({ type: "add", row });
  }, []);
  const addRows = useCallback((rows: PermissionDraftRow[]) => {
    rows.forEach((row) => dispatch({ type: "add", row }));
  }, []);
  const changeRow = useCallback((key: string, changes: Partial<PermissionDraftRow>) => {
    dispatch({ type: "change", key, changes });
  }, []);
  const removeRow = useCallback((key: string) => {
    dispatch({ type: "remove", key });
  }, []);
  const replaceRows = useCallback((rows: PermissionDraftRow[]) => {
    dispatch({ type: "replace_rows", rows });
  }, []);
  const reset = useCallback((rows?: PermissionDraftRow[]) => {
    dispatch({ type: "reset", rows });
  }, []);
  const cancel = useCallback(() => {
    dispatch({ type: "reset" });
  }, []);

  return {
    draft,
    rows: draft.rows,
    diff,
    hasChanges: diff.grants.length > 0 || diff.revokes.length > 0,
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
