import type { HostedAppSchemaChange } from "@/controllers/API/hostedApp"
import { describe, expect, it } from "vitest"
import {
  hasSchemaChange,
  isBreakingOp,
  schemaChangeSummaryI18nKey,
  schemaChangeTarget,
  schemaOpI18nKey,
} from "./schemaChange"

/**
 * The op → label mapping and the "anything to show" rule are what the notice
 * and any future surface (version tab, review view) must agree on; they are
 * asserted here once rather than through each component.
 */

describe("hasSchemaChange", () => {
  it("test_null_and_empty_items_both_mean_nothing_to_show", () => {
    expect(hasSchemaChange(null)).toBe(false)
    expect(hasSchemaChange(undefined)).toBe(false)
    expect(hasSchemaChange({ has_breaking: false, items: [] })).toBe(false)
    expect(
      hasSchemaChange({ has_breaking: false, items: [{ table: "t", column: null, op: "add_table" }] }),
    ).toBe(true)
  })
})

describe("isBreakingOp", () => {
  it("test_drop_and_modify_are_breaking_add_is_not", () => {
    expect(isBreakingOp("drop_table")).toBe(true)
    expect(isBreakingOp("drop_column")).toBe(true)
    expect(isBreakingOp("modify_column")).toBe(true)
    expect(isBreakingOp("add_table")).toBe(false)
    expect(isBreakingOp("add_column")).toBe(false)
    expect(isBreakingOp("rename_column")).toBe(false)
  })
})

describe("schemaOpI18nKey", () => {
  it("test_known_ops_map_and_unknown_falls_back", () => {
    expect(schemaOpI18nKey("modify_column")).toBe("hostedApp.publishStatus.schemaChangeOp.modifyColumn")
    expect(schemaOpI18nKey("add_table")).toBe("hostedApp.publishStatus.schemaChangeOp.addTable")
    expect(schemaOpI18nKey("something_new")).toBe("hostedApp.publishStatus.schemaChangeOp.unknown")
  })
})

describe("schemaChangeTarget", () => {
  it("test_column_rows_are_dotted_table_rows_are_bare", () => {
    expect(schemaChangeTarget({ table: "orders", column: "amount", op: "modify_column" })).toBe("orders.amount")
    expect(schemaChangeTarget({ table: "audit", column: null, op: "drop_table" })).toBe("audit")
  })
})

describe("schemaChangeSummaryI18nKey", () => {
  it("test_summary_follows_has_breaking", () => {
    const breaking: HostedAppSchemaChange = {
      has_breaking: true,
      items: [{ table: "orders", column: "note", op: "drop_column" }],
    }
    const additive: HostedAppSchemaChange = {
      has_breaking: false,
      items: [{ table: "settings", column: null, op: "add_table" }],
    }
    expect(schemaChangeSummaryI18nKey(breaking)).toBe("hostedApp.publishStatus.schemaChangeBreaking")
    expect(schemaChangeSummaryI18nKey(additive)).toBe("hostedApp.publishStatus.schemaChangeAdditive")
  })
})
