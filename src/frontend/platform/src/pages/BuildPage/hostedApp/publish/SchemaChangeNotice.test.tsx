import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"
import { SchemaChangeNotice } from "./SchemaChangeNotice"

/**
 * `react-i18next` is mocked globally (src/test/setup.ts) to echo keys, so the
 * assertions below read as the i18n contract of the notice.
 */

describe("SchemaChangeNotice", () => {
  it("test_renders_nothing_without_a_change", () => {
    const { container, rerender } = render(<SchemaChangeNotice change={null} />)
    expect(container).toBeEmptyDOMElement()
    rerender(<SchemaChangeNotice change={{ has_breaking: false, items: [] }} />)
    expect(container).toBeEmptyDOMElement()
  })

  it("test_lists_every_item_and_tags_only_the_breaking_ones", () => {
    render(
      <SchemaChangeNotice
        change={{
          has_breaking: true,
          items: [
            { table: "orders", column: "amount", op: "modify_column" },
            { table: "orders", column: "note", op: "drop_column" },
            { table: "settings", column: null, op: "add_table" },
          ],
        }}
      />,
    )

    expect(screen.getByTestId("schema-change-notice")).toBeInTheDocument()
    expect(screen.getByText("hostedApp.publishStatus.schemaChangeTitle")).toBeInTheDocument()
    expect(screen.getByText("hostedApp.publishStatus.schemaChangeBreaking")).toBeInTheDocument()

    expect(screen.getByText("orders.amount")).toBeInTheDocument()
    expect(screen.getByText("orders.note")).toBeInTheDocument()
    expect(screen.getByText("settings")).toBeInTheDocument()
    expect(screen.getByText("hostedApp.publishStatus.schemaChangeOp.modifyColumn")).toBeInTheDocument()
    expect(screen.getByText("hostedApp.publishStatus.schemaChangeOp.dropColumn")).toBeInTheDocument()
    expect(screen.getByText("hostedApp.publishStatus.schemaChangeOp.addTable")).toBeInTheDocument()

    // Two breaking rows, one additive: the tag appears exactly twice.
    expect(screen.getAllByText("hostedApp.publishStatus.schemaChangeBreakingTag")).toHaveLength(2)
  })

  it("test_additive_only_change_uses_the_additive_summary_and_no_tag", () => {
    render(
      <SchemaChangeNotice
        change={{
          has_breaking: false,
          items: [{ table: "settings", column: "key", op: "add_column" }],
        }}
      />,
    )
    expect(screen.getByText("hostedApp.publishStatus.schemaChangeAdditive")).toBeInTheDocument()
    expect(screen.getByText("settings.key")).toBeInTheDocument()
    expect(screen.queryByText("hostedApp.publishStatus.schemaChangeBreakingTag")).not.toBeInTheDocument()
  })
})
