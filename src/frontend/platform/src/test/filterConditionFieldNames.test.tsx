import { fireEvent, render, screen } from "@testing-library/react"
import { beforeAll, describe, expect, it, vi } from "vitest"

import { FilterConditionDialog } from "@/pages/Dashboard/components/config/FilterConditionDialog"
import { TooltipProvider } from "@/components/bs-ui/tooltip"

vi.mock("react-i18next", async () => {
  const { default: i18next } = await import("i18next")
  const { default: resources } = await import("../../public/locales/zh-Hans/dashboard.json")
  const instance = i18next.createInstance()
  await instance.init({ lng: "zh-Hans", resources: { "zh-Hans": { dashboard: resources } }, defaultNS: "dashboard" })
  return { useTranslation: () => ({ t: instance.t.bind(instance) }) }
})

beforeAll(() => {
  Element.prototype.scrollIntoView = vi.fn()
  Element.prototype.hasPointerCapture = vi.fn(() => false)
  Element.prototype.setPointerCapture = vi.fn()
  Element.prototype.releasePointerCapture = vi.fn()
})

describe("filter condition field names", () => {
  it("uses dataset names for untranslated fields and keeps configured display names", () => {
    const fields = [
      { fieldCode: "uploader_department_name", displayName: "上传人部门", fieldType: "string", role: "dimension" },
      { fieldCode: "belonging_company_name", displayName: "所属公司", fieldType: "string", role: "dimension" },
      { fieldCode: "original_space_name", displayName: "原始上传库", fieldType: "string", role: "dimension" },
      { fieldCode: "original_upload_company_name", displayName: "原始所属公司", fieldType: "string", role: "dimension" },
      { fieldCode: "original_upload_department_name", displayName: "原始所属部门", fieldType: "string", role: "dimension" },
      { fieldCode: "original_upload_office_name", displayName: "原始所属科室", fieldType: "string", role: "dimension" },
      { fieldCode: "original_upload_squad_name", displayName: "原始所属班组", fieldType: "string", role: "dimension" },
      { fieldCode: "uploader_office_name", displayName: "上传人科室", fieldType: "string", role: "dimension" },
    ] as const
    render(<TooltipProvider><FilterConditionDialog open onOpenChange={vi.fn()} onChange={vi.fn()} value={null}
      fields={[...fields]} dataset_code="mid_knowledge_space_content_stat"
      {...{ dimensions: [{ fieldId: "uploader_office_name", displayName: "自定义科室名称" }] }} /></TooltipProvider>)
    fireEvent.keyDown(screen.getByRole("combobox"), { key: "ArrowDown" })
    expect(screen.getByRole("option", { name: "上传人部门" })).toBeInTheDocument()
    expect(screen.getByRole("option", { name: "所属公司" })).toBeInTheDocument()
    for (const name of ["原始上传库", "原始所属公司", "原始所属部门", "原始所属科室", "原始所属班组"]) {
      expect(screen.getByRole("option", { name })).toBeInTheDocument()
    }
    expect(screen.getByRole("option", { name: "自定义科室名称" })).toBeInTheDocument()
  })
})
