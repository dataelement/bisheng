import { describe, expect, it, vi } from "vitest"
import { getDashboard } from "../controllers/API/dashboard"
import request from "../controllers/request"
import type { Dashboard, DashboardComponent, DataConfig } from "../pages/Dashboard/types/dataConfig"
import zhDashboard from "../../public/locales/zh-Hans/dashboard.json"
import enDashboard from "../../public/locales/en-US/dashboard.json"
import jaDashboard from "../../public/locales/ja/dashboard.json"

vi.mock("../controllers/request", () => ({ default: { get: vi.fn() } }))

function legacyComponent(
  dataset = "mid_user_increment", alias = "实际登录人数",
  fieldId = "logged_in_employee_count", fieldName = "实际登录人数",
): DashboardComponent {
  return {
    id: "login-card",
    dataset_code: dataset,
    title: alias,
    data_config: {
      metrics: [{ fieldId, fieldName, displayName: alias }],
      fieldOrder: [{ fieldId, fieldType: "metric", displayName: alias }],
    },
    style_config: { title: alias },
  } as unknown as DashboardComponent
}

describe("user metric labels", () => {
  it("updates the dataset picker labels in all supported languages", () => {
    expect(zhDashboard.logged_in_employee_count).toBe("累计登录人次")
    expect(zhDashboard.active_employee_count).toBe("全员有效用户数")
    expect(zhDashboard.participation_rate).toBe("全员参与度占比")
    expect(enDashboard.logged_in_employee_count).toBe("Cumulative Logged-in Person-times")
    expect(jaDashboard.logged_in_employee_count).toBe("累計ログイン人回")
    expect(enDashboard.active_employee_count).toBe("Total Effective Users")
    expect(jaDashboard.active_employee_count).toBe("有効ユーザー総数")
  })

  it.each([
    ["mid_user_increment", "logged_in_employee_count", "累积登录人数", "累计登录人次"],
    ["mid_user_increment", "logged_in_employee_count", "累计登录人数", "累计登录人次"],
    ["mid_user_increment", "logged_in_employee_count", "实际登录人数", "累计登录人次"],
    ["mid_user_daily_participation", "logged_in_employee_count", "累计实际登录人数", "累计登录人次"],
    ["mid_user_increment", "active_employee_count", "全员总数", "全员有效用户数"],
    ["mid_user_daily_participation", "active_employee_count", "有效人员总数", "全员有效用户数"],
    ["mid_user_increment", "participation_rate", "全员参与占比", "全员参与度占比"],
  ])("renames saved labels for %s %s without mutating the response", async (dataset, fieldId, oldLabel, newLabel) => {
    const component = legacyComponent(dataset, oldLabel, fieldId, oldLabel)
    const dashboard = { id: "177", components: [component] } as Dashboard
    vi.mocked(request.get).mockResolvedValueOnce(dashboard)

    const result = await getDashboard("177")
    const renamed = result.components[0]
    expect(renamed.title).toBe(newLabel)
    expect(renamed.style_config.title).toBe(newLabel)
    expect((renamed.data_config as DataConfig).metrics[0]).toMatchObject({
      fieldId, fieldName: newLabel, displayName: newLabel,
    })
    expect((renamed.data_config as DataConfig).fieldOrder[0]).toMatchObject({ displayName: newLabel })
    expect(component.title).toBe(oldLabel)
    expect(component.style_config.title).toBe(oldLabel)
  })

  it.each([
    ["mid_user_increment", "本部门登录人员", "logged_in_employee_count"],
    ["mid_user_increment", "本部门有效人员", "active_employee_count"],
    ["custom_dataset", "实际登录人数", "logged_in_employee_count"],
  ])("preserves custom labels and other datasets: %s", async (dataset, alias, fieldId) => {
    vi.mocked(request.get).mockResolvedValueOnce({ id: "177", components: [legacyComponent(dataset, alias, fieldId)] })
    const result = await getDashboard("177")
    expect(result.components[0].title).toBe(alias)
    expect(result.components[0].style_config.title).toBe(alias)
    expect((result.components[0].data_config as DataConfig).metrics[0].displayName).toBe(alias)
  })
})
