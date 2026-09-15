import userEvent from "@testing-library/user-event"
import type { InputHTMLAttributes } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import {
  getPersonalTokenSettingApi,
  listPersonalTokensApi,
  updatePersonalTokenSettingApi,
} from "@/controllers/API/personalToken"
import { captureAndAlertRequestErrorHoc } from "@/controllers/request"
import { PersonalToken } from "@/pages/SystemPage/components/PersonalToken"
import { render, screen, waitFor } from "@/test/test-utils"
import type { PersonalTokenSetting } from "@/types/api/openApi"
import { message } from "@/components/bs-ui/toast/use-toast"
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm"
import { revokePersonalTokenApi } from "@/controllers/API/personalToken"

vi.mock("@/controllers/API/personalToken", () => ({
  getPersonalTokenSettingApi: vi.fn(),
  listPersonalTokensApi: vi.fn(),
  revokePersonalTokenApi: vi.fn(),
  updatePersonalTokenSettingApi: vi.fn(),
}))

vi.mock("@/components/bs-ui/alertDialog/useConfirm", () => ({
  bsConfirm: vi.fn(),
}))

vi.mock("@/controllers/request", () => ({
  captureAndAlertRequestErrorHoc: vi.fn(),
}))

vi.mock("@/components/bs-icons", () => ({
  LoadIcon: () => <span data-testid="loading-icon" />,
}))

vi.mock("@/components/bs-ui/input", () => ({
  Input: (props: InputHTMLAttributes<HTMLInputElement>) => <input {...props} />,
}))

vi.mock("@/components/bs-ui/toast/use-toast", () => ({
  message: vi.fn(),
}))

const initialSetting: PersonalTokenSetting = {
  deployment_enabled: true,
  pat_enabled: false,
  effective_enabled: false,
  pat_ttl_days: 365,
  data_scope: "all_visible",
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((next) => {
    resolve = next
  })
  return { promise, resolve }
}

describe("personal-token tenant settings interaction", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(getPersonalTokenSettingApi).mockResolvedValue(initialSetting)
    vi.mocked(listPersonalTokensApi).mockResolvedValue({ data: [], total: 0 })
    vi.mocked(captureAndAlertRequestErrorHoc).mockImplementation(async (request) => {
      try {
        return await request
      } catch {
        return undefined
      }
    })
  })

  it("locks the settings while saving and reports success", async () => {
    const pending = deferred<PersonalTokenSetting>()
    vi.mocked(updatePersonalTokenSettingApi).mockReturnValue(pending.promise)
    const user = userEvent.setup()

    render(<PersonalToken />)

    const saveButton = await screen.findByRole("button", { name: "save" })
    const tenantSwitch = screen.getByRole("switch")
    const ttlInput = screen.getByRole("spinbutton")
    expect(ttlInput).toHaveValue(365)
    await user.click(saveButton)

    expect(updatePersonalTokenSettingApi).toHaveBeenCalledTimes(1)
    expect(updatePersonalTokenSettingApi).toHaveBeenCalledWith({
      pat_enabled: false,
      pat_ttl_days: 365,
      data_scope: "all_visible",
    })
    expect(saveButton).toBeDisabled()
    expect(saveButton).toHaveAttribute("aria-busy", "true")
    expect(tenantSwitch).toBeDisabled()
    expect(ttlInput).toBeDisabled()
    await user.click(saveButton)
    expect(updatePersonalTokenSettingApi).toHaveBeenCalledTimes(1)

    pending.resolve({ ...initialSetting, pat_enabled: true, effective_enabled: true })

    await waitFor(() => expect(saveButton).toBeEnabled())
    // No locationContext provider here, so the component sees a single-tenant
    // deployment and reports with the tenant-free key; the tenancy switch
    // itself is covered by openApiManagementTenantCopy.test.tsx.
    expect(message).toHaveBeenCalledWith({
      title: "prompt",
      variant: "success",
      description: "openApiManagement.personalToken.settingsSavedSingle",
    })
  })

  it("delegates a failed save to the shared error interaction and unlocks the settings", async () => {
    vi.mocked(updatePersonalTokenSettingApi).mockRejectedValue(new Error("save failed"))
    const user = userEvent.setup()

    render(<PersonalToken />)
    const saveButton = await screen.findByRole("button", { name: "save" })
    await user.click(saveButton)

    expect(captureAndAlertRequestErrorHoc).toHaveBeenCalledTimes(1)
    await waitFor(() => expect(saveButton).toBeEnabled())
    expect(message).not.toHaveBeenCalled()
  })

  it("renders localized permission names instead of raw scope codes", async () => {
    vi.mocked(listPersonalTokensApi).mockResolvedValue({
      data: [
        {
          id: 1,
          holder_user_id: 12,
          holder_name: "User 12",
          key_mask: "bs_pat_****",
          scopes: ["knowledge:read"],
          expires_at: "2026-10-09T00:00:00",
          revoked_at: null,
          last_used_at: null,
          revoke_reason: null,
          is_valid: true,
          holder_is_admin: false,
          create_time: "2026-09-09T00:00:00",
        },
      ],
      total: 1,
    })

    render(<PersonalToken />)

    expect(
      await screen.findByText("openApiManagement.scopes.knowledge_read.label"),
    ).toBeInTheDocument()
    expect(screen.queryByText("knowledge:read")).not.toBeInTheDocument()
  })

  it("confirms before tightening the data scope and sends it on save", async () => {
    vi.mocked(updatePersonalTokenSettingApi).mockResolvedValue({
      ...initialSetting,
      data_scope: "personal_only",
    })
    vi.mocked(bsConfirm).mockImplementation((params: { onOk?: (next: () => void) => void }) => {
      params.onOk?.(vi.fn())
    })
    const user = userEvent.setup()

    render(<PersonalToken />)
    await screen.findByRole("button", { name: "save" })
    await user.click(screen.getByRole("radio", { name: /scopeModeOwnOnly/ }))
    await user.click(screen.getByRole("button", { name: "save" }))

    expect(bsConfirm).toHaveBeenCalledWith(
      expect.objectContaining({
        title: "openApiManagement.personalToken.tightenConfirmTitle",
        desc: "openApiManagement.personalToken.tightenConfirmBody",
      }),
    )
    await waitFor(() =>
      expect(updatePersonalTokenSettingApi).toHaveBeenCalledWith({
        pat_enabled: false,
        pat_ttl_days: 365,
        data_scope: "personal_only",
      }),
    )
  })

  it("widening back needs no confirmation", async () => {
    vi.mocked(getPersonalTokenSettingApi).mockResolvedValue({
      ...initialSetting,
      data_scope: "personal_only",
    })
    vi.mocked(updatePersonalTokenSettingApi).mockResolvedValue(initialSetting)
    const user = userEvent.setup()

    render(<PersonalToken />)
    await screen.findByRole("button", { name: "save" })
    await user.click(screen.getByRole("radio", { name: /scopeModeAll/ }))
    await user.click(screen.getByRole("button", { name: "save" }))

    expect(bsConfirm).not.toHaveBeenCalled()
    await waitFor(() =>
      expect(updatePersonalTokenSettingApi).toHaveBeenCalledWith({
        pat_enabled: false,
        pat_ttl_days: 365,
        data_scope: "all_visible",
      }),
    )
  })

  it("revoking a key asks for confirmation first", async () => {
    vi.mocked(listPersonalTokensApi).mockResolvedValue({
      data: [{
        id: 3,
        holder_user_id: 12,
        holder_name: "User 12",
        key_mask: "bs_pat_****",
        scopes: ["knowledge:read"],
        expires_at: null,
        revoked_at: null,
        last_used_at: null,
        revoke_reason: null,
        is_valid: true,
        holder_is_admin: false,
        create_time: null,
      }],
      total: 1,
    })
    vi.mocked(bsConfirm).mockImplementation((params: { onOk?: (next: () => void) => void }) => {
      params.onOk?.(vi.fn())
    })
    vi.mocked(revokePersonalTokenApi).mockResolvedValue(undefined)
    const user = userEvent.setup()

    render(<PersonalToken />)
    const revokeButton = await screen.findByRole("button", { name: "openApiManagement.actions.revoke" })
    await user.click(revokeButton)

    expect(bsConfirm).toHaveBeenCalledWith(
      expect.objectContaining({ title: "openApiManagement.personalToken.revokeConfirmTitle" }),
    )
    await waitFor(() => expect(revokePersonalTokenApi).toHaveBeenCalledWith(3))
  })
})
