import { fireEvent, render, screen } from "@/test/test-utils"
import type { ApiKeyIssued } from "@/types/api/openApi"
import { describe, expect, it, vi } from "vitest"
import { KeyRevealDialog } from "@/pages/SystemPage/components/ServiceAccount/KeyRevealDialog"

vi.mock("@/utils", () => ({ copyText: vi.fn() }))

const baseKey: ApiKeyIssued = {
  id: 1,
  subject_kind: "service_account",
  subject_id: 20,
  name: "integration",
  key_mask: "bs-sak-********abcd",
  scopes: ["chat:invoke"],
  delegate_scopes: [],
  expires_at: null,
  revoked_at: null,
  last_used_at: null,
  revoke_reason: null,
  is_valid: true,
  create_time: null,
  plaintext: "bs-sak-plain-secret",
}

function expandVerify() {
  fireEvent.click(
    screen.getByRole("button", { name: /openApiManagement.keys.verifyTitle/ }),
  )
}

describe("KeyRevealDialog", () => {
  it("keeps the self-check command collapsed until asked for", () => {
    render(<KeyRevealDialog issuedKey={baseKey} onClose={() => {}} />)

    expect(screen.getByText("bs-sak-plain-secret")).toBeInTheDocument()
    expect(screen.queryByText(/auth\/whoami/)).not.toBeInTheDocument()

    expandVerify()

    const command = screen.getByText(/auth\/whoami/).textContent || ""
    expect(command).toContain("Authorization: Bearer bs-sak-plain-secret")
    expect(command).not.toContain("X-On-Behalf-Of")
    expect(
      screen.queryByText(/openApiManagement.keys.verifyDelegateHint/),
    ).not.toBeInTheDocument()
  })

  it("adds the acting user to the command for a delegated key", () => {
    const delegated: ApiKeyIssued = {
      ...baseKey,
      scopes: ["chat:invoke", "delegate"],
      delegate_scopes: [
        { subject_type: "department", subject_id: 5, subject_name: "R&D" },
        { subject_type: "user", subject_id: 823, subject_name: "Alice" },
      ],
    }
    render(<KeyRevealDialog issuedKey={delegated} onClose={() => {}} />)
    expandVerify()

    const command = screen.getByText(/auth\/whoami/).textContent || ""
    expect(command).toContain('X-On-Behalf-Of: 823"')
    expect(
      screen.getByText(/openApiManagement.keys.verifyDelegateHint/),
    ).toBeInTheDocument()
  })

  it("falls back to a placeholder when only departments are delegated", () => {
    const delegated: ApiKeyIssued = {
      ...baseKey,
      scopes: ["chat:invoke", "delegate"],
      delegate_scopes: [
        { subject_type: "department", subject_id: 5, subject_name: "R&D" },
      ],
    }
    render(<KeyRevealDialog issuedKey={delegated} onClose={() => {}} />)
    expandVerify()

    expect(screen.getByText(/auth\/whoami/).textContent).toContain(
      "X-On-Behalf-Of: <USER_ID>",
    )
  })
})
