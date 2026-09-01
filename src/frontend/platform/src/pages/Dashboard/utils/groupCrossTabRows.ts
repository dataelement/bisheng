// F058 AC-12/AC-13: group PivotTable rows by the finest actively-filtered
// organization-hierarchy dimension, so the table can render "outer group + inner
// sub-table" instead of a flat multi-column row. Pure client-side transform over the
// already-flat `PivotTableRow[]` produced by transformPivotData — the backend's
// aggregation/response contract is unchanged (see spec.md AD-02).

export interface PivotTableRow {
  key: string[]
  values: number[]
  total: number
}

export interface GroupedPivotRows {
  groupKey: string
  groupLabel: string
  childRows: PivotTableRow[]
}

export interface DimensionQueryFilter {
  fieldId: string
  values: unknown[]
}

export const ORG_LEVEL_ORDER = ["company", "dept", "office", "squad"] as const
export type OrgLevel = (typeof ORG_LEVEL_ORDER)[number]

const ORG_LEVEL_BY_SUFFIX: Record<string, OrgLevel> = {
  company_name: "company",
  department_name: "dept",
  office_name: "office",
  squad_name: "squad",
}

const ORG_FIELD_PREFIXES = ["belonging_", "uploader_"]

// F058 AC-11: person-name dimensions that must show their paired department alongside
// them (same visual cell) to disambiguate same-named people across departments. Scoped
// to pairs that are both actually configured as row dimensions on the chart — see
// mergePersonDedupColumn's docstring for why this doesn't try to silently inject the
// paired field into the query when the author didn't configure it.
export const PERSON_NAME_DEDUP_PAIR: Record<string, string> = {
  uploader_user_name: "uploader_department_name",
}

// Shared by DimensionFilter.tsx (AC-01/02/03: full-roster org filters, ordering) and the
// grouping logic below (AC-12/13) — one source of truth for "is this an org-hierarchy field".
export function orgLevelForField(fieldId: string): OrgLevel | null {
  for (const prefix of ORG_FIELD_PREFIXES) {
    if (fieldId.startsWith(prefix)) {
      return ORG_LEVEL_BY_SUFFIX[fieldId.slice(prefix.length)] ?? null
    }
  }
  return null
}

/**
 * Which row-dimension index (into `rowFieldIds` / `PivotTableRow.key`) to group by.
 *
 * Returns null when either:
 * - no configured row dimension is an org-hierarchy field with an actively selected
 *   filter value (nothing to group by — render the flat table as today), or
 * - the finest actively-filtered org level is already the last configured row
 *   dimension, i.e. there is no next level to nest as a sub-table (AC-13: filtered
 *   down to 班组 — the finest tier — renders flat, not grouped).
 */
export function resolveGroupDimensionIndex(
  rowFieldIds: string[],
  dimensionFilters: DimensionQueryFilter[] | undefined,
): number | null {
  const activeFieldIds = new Set(
    (dimensionFilters || [])
      .filter(filter => (filter.values?.length ?? 0) > 0)
      .map(filter => filter.fieldId),
  )

  let bestIndex: number | null = null
  let bestRank = -1
  rowFieldIds.forEach((fieldId, index) => {
    const level = orgLevelForField(fieldId)
    if (!level || !activeFieldIds.has(fieldId)) return
    const rank = ORG_LEVEL_ORDER.indexOf(level)
    if (rank > bestRank) {
      bestRank = rank
      bestIndex = index
    }
  })

  if (bestIndex === null) return null
  if (bestIndex >= rowFieldIds.length - 1) return null
  return bestIndex
}

/**
 * Group flat pivot rows by `row.key[groupDimensionIndex]`. Returns null (render flat,
 * unchanged) when `groupDimensionIndex` is null.
 */
/**
 * Which row-dimension indices to merge for person-name disambiguation (AC-11): the
 * person field's index and its paired department field's index, only when BOTH are
 * actually configured as row dimensions on the chart.
 *
 * Deliberately does NOT try to silently add the department field to the query when the
 * chart author only configured the person-name field: the query request for a saved
 * dashboard component can be built server-side from a stored `data_config` (id-based
 * viewing), so a client-side-only injection would be inconsistent between "editing a
 * chart" and "viewing a saved dashboard". If disambiguation is wanted, the chart must be
 * configured with both dimensions — this only changes how an already-fetched pair
 * *displays* (one merged cell instead of two columns).
 */
export function resolvePersonDedupIndices(
  rowFieldIds: string[],
): { personIndex: number, deptIndex: number } | null {
  for (const [personField, deptField] of Object.entries(PERSON_NAME_DEDUP_PAIR)) {
    const personIndex = rowFieldIds.indexOf(personField)
    const deptIndex = rowFieldIds.indexOf(deptField)
    if (personIndex !== -1 && deptIndex !== -1) {
      return { personIndex, deptIndex }
    }
  }
  return null
}

/** Merge `values[deptIndex]` into `values[personIndex]` as "name(dept)" and drop the
 * department entry, preserving the relative order of all other entries. */
export function mergePersonDedupValues(
  values: string[],
  personIndex: number,
  deptIndex: number,
): string[] {
  return values
    .map((value, index) => (index === personIndex ? `${value}(${values[deptIndex] || "未分类"})` : value))
    .filter((_value, index) => index !== deptIndex)
}

export function groupCrossTabRows(
  rows: PivotTableRow[],
  groupDimensionIndex: number | null,
): GroupedPivotRows[] | null {
  if (groupDimensionIndex === null) return null

  const groups = new Map<string, GroupedPivotRows>()
  for (const row of rows) {
    const groupLabel = row.key[groupDimensionIndex] ?? "未分类"
    if (!groups.has(groupLabel)) {
      groups.set(groupLabel, { groupKey: groupLabel, groupLabel, childRows: [] })
    }
    groups.get(groupLabel)!.childRows.push(row)
  }
  return Array.from(groups.values())
}
