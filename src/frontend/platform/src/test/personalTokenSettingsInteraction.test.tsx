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
import { toast } from "@/components/bs-ui/toast/use-toast"

vi.mock("@/controllers/API/personalToken", () => ({
  getPersonalTokenSettingApi: vi.fn(),
  listPersonalTokensApi: vi.fn(),
  revokePersonalTokenApi: vi.fn(),
  revokePersonalTokensByHolderApi: vi.fn(),
  updatePersonalTokenSettingApi: vi.fn(),
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
  toast: vi.fn(),
}))

const initialSetting: PersonalTokenSetting = {
  deployment_enabled: true,
  pat_enabled: false,
  effective_enabled: false,
  pat_ttl_days: 30,
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
    await user.click(saveButton)

    expect(updatePersonalTokenSettingApi).toHaveBeenCalledTimes(1)
    expect(saveButton).toBeDisabled()
    expect(saveButton).toHaveAttribute("aria-busy", "true")
    expect(tenantSwitch).toBeDisabled()
    expect(ttlInput).toBeDisabled()
    await user.click(saveButton)
    expect(updatePersonalTokenSettingApi).toHaveBeenCalledTimes(1)

    pending.resolve({ ...initialSetting, pat_enabled: true, effective_enabled: true })

    await waitFor(() => expect(saveButton).toBeEnabled())
    expect(toast).toHaveBeenCalledWith({
      title: "prompt",
      variant: "success",
      description: "openApiManagement.personalToken.settingsSaved",
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
    expect(toast).not.toHaveBeenCalled()
  })
})
