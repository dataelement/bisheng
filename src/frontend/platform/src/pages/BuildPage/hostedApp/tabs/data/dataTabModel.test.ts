import type { HostedAppColumn, HostedAppTableSchema } from "@/controllers/API/hostedAppData"
import { describe, expect, it } from "vitest"
import {
  buildRowPatch,
  coerceInput,
  columnAffinity,
  draftFromRow,
  editableColumns,
  exportFileName,
  formatCell,
  isNullCell,
  orderDirection,
  toggleOrder,
} from "./dataTabModel"

function column(name: string, type: string, extra: Partial<HostedAppColumn> = {}): HostedAppColumn {
  return { name, type, notnull: false, default: null, pk: 0, editable: true, ...extra }
}

const schema: HostedAppTableSchema = {
  table: "users",
  columns: [
    column("id", "INTEGER", { pk: 1 }),
    column("name", "TEXT", { notnull: true }),
    column("score", "REAL"),
    column("avatar", "BLOB", { editable: false }),
  ],
  key: { column: "id", kind: "primary_key" },
  editable: true,
}

describe("columnAffinity", () => {
  it("follows SQLite's declared-type rules in the engine's order", () => {
    // INT wins over anything else in the name, which is why a "POINT" column
    // is an integer column to SQLite — and therefore to us.
    expect(columnAffinity("INTEGER")).toBe("integer")
    expect(columnAffinity("bigint")).toBe("integer")
    expect(columnAffinity("POINT")).toBe("integer")
    expect(columnAffinity("VARCHAR(20)")).toBe("text")
    expect(columnAffinity("CLOB")).toBe("text")
    expect(columnAffinity("REAL")).toBe("real")
    expect(columnAffinity("DOUBLE PRECISION")).toBe("real")
    expect(columnAffinity("NUMERIC")).toBe("numeric")
    expect(columnAffinity("BOOLEAN")).toBe("numeric")
    expect(columnAffinity("")).toBe("text")
    expect(columnAffinity(undefined)).toBe("text")
  })
})

describe("formatCell / isNullCell", () => {
  it("prints NULL as nothing and never as the word null", () => {
    expect(formatCell(null)).toBe("")
    expect(formatCell(undefined)).toBe("")
    expect(isNullCell(null)).toBe(true)
    expect(isNullCell("")).toBe(false)
  })

  it("prints scalars as text", () => {
    expect(formatCell(0)).toBe("0")
    expect(formatCell(false)).toBe("false")
    expect(formatCell("<blob 12 bytes>")).toBe("<blob 12 bytes>")
  })
})

describe("coerceInput", () => {
  it("turns typed digits into a number only where the column stores numbers", () => {
    expect(coerceInput("12", column("n", "INTEGER"))).toBe(12)
    expect(coerceInput(" -3 ", column("n", "INTEGER"))).toBe(-3)
    expect(coerceInput("1.5", column("n", "REAL"))).toBe(1.5)
    expect(coerceInput("1e3", column("n", "NUMERIC"))).toBe(1000)
    expect(coerceInput("12", column("n", "TEXT"))).toBe("12")
    expect(coerceInput("12", column("n", ""))).toBe("12")
  })

  it("keeps text that is not a whole number for the column instead of truncating it", () => {
    // "1.5" in an INTEGER column is sent as text; the manager decides, and a
    // silent Math.trunc here would have rewritten the owner's value.
    expect(coerceInput("1.5", column("n", "INTEGER"))).toBe("1.5")
    expect(coerceInput("abc", column("n", "INTEGER"))).toBe("abc")
    expect(coerceInput("", column("n", "INTEGER"))).toBe("")
    expect(coerceInput("0x10", column("n", "INTEGER"))).toBe("0x10")
    expect(coerceInput("99999999999999999999", column("n", "INTEGER"))).toBe("99999999999999999999")
  })
})

describe("editableColumns", () => {
  it("drops the key column and binary columns", () => {
    expect(editableColumns(schema).map((c) => c.name)).toEqual(["name", "score"])
  })

  it("offers nothing on a table the manager marked read-only", () => {
    expect(editableColumns({ ...schema, editable: false })).toEqual([])
  })
})

describe("draftFromRow / buildRowPatch", () => {
  const columns = editableColumns(schema)
  const original = { id: 1, name: "alice", score: null, avatar: "<blob 3 bytes>" }

  it("starts from the row and sends nothing when nothing changed", () => {
    const draft = draftFromRow(columns, original)
    expect(draft).toEqual({
      name: { text: "alice", setNull: false },
      score: { text: "", setNull: true },
    })
    expect(buildRowPatch(columns, original, draft)).toEqual({})
  })

  it("sends only the changed columns, coerced to the column's type", () => {
    const draft = draftFromRow(columns, original)
    draft.score = { text: "4.5", setNull: false }
    expect(buildRowPatch(columns, original, draft)).toEqual({ score: 4.5 })
  })

  it("treats retyping the same value as no change", () => {
    const draft = draftFromRow(columns, { ...original, score: 4.5 })
    draft.score = { text: "4.5", setNull: false }
    expect(buildRowPatch(columns, { ...original, score: 4.5 }, draft)).toEqual({})
  })

  it("distinguishes an empty string from NULL", () => {
    const draft = draftFromRow(columns, original)
    draft.name = { text: "", setNull: false }
    expect(buildRowPatch(columns, original, draft)).toEqual({ name: "" })
    draft.name = { text: "", setNull: true }
    expect(buildRowPatch(columns, original, draft)).toEqual({ name: null })
  })

  it("never includes the key or a binary column, whatever the draft says", () => {
    const draft = {
      ...draftFromRow(columns, original),
      id: { text: "2", setNull: false },
      avatar: { text: "x", setNull: false },
    }
    expect(buildRowPatch(columns, original, draft)).toEqual({})
  })
})

describe("toggleOrder / orderDirection", () => {
  it("cycles none → asc → desc → none per column", () => {
    expect(toggleOrder("", "name")).toBe("name")
    expect(toggleOrder("name", "name")).toBe("-name")
    expect(toggleOrder("-name", "name")).toBe("")
    expect(toggleOrder("-name", "score")).toBe("score")
    expect(orderDirection("name", "name")).toBe("asc")
    expect(orderDirection("-name", "name")).toBe("desc")
    expect(orderDirection("-name", "score")).toBeNull()
  })
})

describe("exportFileName", () => {
  it("keeps the app name readable and the file system happy", () => {
    expect(exportFileName("sales", "users")).toBe("sales-users.csv")
    expect(exportFileName("My App / v2", "users")).toBe("My-App-v2-users.csv")
    expect(exportFileName("", "users")).toBe("app-users.csv")
  })
})
