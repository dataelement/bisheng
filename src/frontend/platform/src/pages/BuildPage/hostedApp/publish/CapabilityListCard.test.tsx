import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"
import { CapabilityListCard } from "./CapabilityListCard"

/**
 * `react-i18next` is mocked globally (src/test/setup.ts) to echo keys, so the
 * assertions below read as the i18n contract of the card.
 */

describe("CapabilityListCard", () => {
  it("test_an_application_that_declares_nothing_says_so", () => {
    // Not an empty section: a card that disappears reads as "the page failed to
    // load it", which sends the owner looking for a problem that is not there.
    render(<CapabilityListCard capabilities={[]} />)

    expect(screen.getByTestId("capability-list-card")).toBeInTheDocument()
    expect(screen.getByText("hostedApp.publishStatus.capabilityNone")).toBeInTheDocument()
  })

  it("test_missing_capabilities_render_as_none_rather_than_crashing", () => {
    render(<CapabilityListCard capabilities={undefined} />)

    expect(screen.getByText("hostedApp.publishStatus.capabilityNone")).toBeInTheDocument()
  })

  it("test_each_row_shows_its_kind_and_the_name_the_owner_wrote", () => {
    render(
      <CapabilityListCard
        capabilities={[
          { kind: "model", name: "qwen-max", revoked: false, reason: "ok" },
          { kind: "knowledge", name: "Product handbook", revoked: false, reason: "ok" },
        ]}
      />,
    )

    expect(screen.getByText("qwen-max")).toBeInTheDocument()
    expect(screen.getByText("Product handbook")).toBeInTheDocument()
    expect(screen.getByText("hostedApp.publishStatus.capabilityKindModel")).toBeInTheDocument()
    expect(screen.getByText("hostedApp.publishStatus.capabilityKindKnowledge")).toBeInTheDocument()
    // Nothing is marked when nothing is broken — the mark carries information
    // only if a healthy row does not carry one too.
    expect(
      screen.queryByText("hostedApp.publishStatus.capabilityRevokedTag"),
    ).not.toBeInTheDocument()
  })

  it("test_a_revoked_capability_is_marked_with_its_reason", () => {
    render(
      <CapabilityListCard
        capabilities={[
          { kind: "knowledge", name: "Product handbook", revoked: false, reason: "ok" },
          { kind: "knowledge", name: "Finance archive", revoked: true, reason: "revoked" },
          { kind: "knowledge", name: "Duplicate name", revoked: true, reason: "ambiguous" },
        ]}
      />,
    )

    expect(screen.getAllByText("hostedApp.publishStatus.capabilityRevokedTag")).toHaveLength(2)
    expect(
      screen.getByText("hostedApp.publishStatus.capabilityReasonRevoked"),
    ).toBeInTheDocument()
    expect(
      screen.getByText("hostedApp.publishStatus.capabilityReasonAmbiguous"),
    ).toBeInTheDocument()
    // The healthy row is still listed; one dead capability does not hide the rest.
    expect(screen.getByText("Product handbook")).toBeInTheDocument()
  })

  it("test_an_unknown_reason_still_says_something", () => {
    // The backend's reason vocabulary may grow; a row that renders a raw enum —
    // or nothing at all next to an "unavailable" tag — is worse than a generic line.
    render(
      <CapabilityListCard
        capabilities={[{ kind: "model", name: "qwen-max", revoked: true, reason: "future-reason" }]}
      />,
    )

    expect(
      screen.getByText("hostedApp.publishStatus.capabilityReasonUnresolvable"),
    ).toBeInTheDocument()
  })

  it("test_the_card_offers_no_way_to_change_a_declaration", () => {
    // AC-54 / AC-61: capabilities are declared in bisheng-app.yaml and take
    // effect through a publish. A control here would be a second, unapproved
    // way to change what an application may call.
    const { container } = render(
      <CapabilityListCard
        capabilities={[{ kind: "model", name: "qwen-max", revoked: false, reason: "ok" }]}
      />,
    )

    expect(container.querySelectorAll("input, select, textarea, button")).toHaveLength(0)
  })
})
