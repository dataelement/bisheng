import type {
  HostedAppSchemaChange,
  HostedAppSchemaChangeItem,
} from "@/controllers/API/hostedApp"

/**
 * Pure logic behind the structure-change notice — kept out of the component so
 * the op → label mapping and the "is there anything to show" rule can be tested
 * without a DOM, and so both surfaces that render the change agree on them.
 */

/** The operations the backend gate requires confirmation for (schema_evolution_service.BREAKING_OPS). */
const BREAKING_OPS: ReadonlySet<string> = new Set([
  "drop_table",
  "drop_column",
  "modify_column",
])

const OP_I18N: Record<string, string> = {
  add_table: "hostedApp.publishStatus.schemaChangeOp.addTable",
  drop_table: "hostedApp.publishStatus.schemaChangeOp.dropTable",
  add_column: "hostedApp.publishStatus.schemaChangeOp.addColumn",
  drop_column: "hostedApp.publishStatus.schemaChangeOp.dropColumn",
  modify_column: "hostedApp.publishStatus.schemaChangeOp.modifyColumn",
}

/**
 * Whether the notice renders at all.
 *
 * `null` is the backend's "nothing changed", but an object with an empty
 * `items` list must read the same way: a title over an empty list looks like a
 * loading failure, not like "no change".
 */
export function hasSchemaChange(
  change: HostedAppSchemaChange | null | undefined,
): change is HostedAppSchemaChange {
  return !!change && Array.isArray(change.items) && change.items.length > 0
}

/**
 * Judged per item from `op`, not from the top-level `has_breaking`: the flag
 * says whether the *release* needed confirmation, the row tag says which line
 * is the reason.
 */
export function isBreakingOp(op: string): boolean {
  return BREAKING_OPS.has(op)
}

/** Label key for an op; an op this build does not know falls back to the neutral word. */
export function schemaOpI18nKey(op: string): string {
  return OP_I18N[op] ?? "hostedApp.publishStatus.schemaChangeOp.unknown"
}

/** `orders.amount` for a column, `orders` for a table. */
export function schemaChangeTarget(item: HostedAppSchemaChangeItem): string {
  return item.column ? `${item.table}.${item.column}` : item.table
}

/**
 * The one-sentence summary above the list: breaking changes were confirmed by
 * the publisher; additive ones go through on their own.
 */
export function schemaChangeSummaryI18nKey(change: HostedAppSchemaChange): string {
  return change.has_breaking
    ? "hostedApp.publishStatus.schemaChangeBreaking"
    : "hostedApp.publishStatus.schemaChangeAdditive"
}
