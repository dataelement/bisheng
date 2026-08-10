import {
  departmentMatchesKeyword,
  resolveDepartmentDisplayName,
} from "./departmentDisplayName";

describe("department display name", () => {
  test.each([
    [{ displayName: "质管", shortName: "质量", name: "质量管理部" }, "质管"],
    [{ shortName: " 质量 ", name: "质量管理部" }, "质量"],
    [{ shortName: "   ", name: "质量管理部" }, "质量管理部"],
    [{ name: "质量管理部" }, "质量管理部"],
  ])("uses display, short and formal name fallback", (input, expected) => {
    expect(resolveDepartmentDisplayName(input)).toBe(expected);
  });

  it("matches both the formal name and short name", () => {
    const department = { displayName: "质量", shortName: "质量", name: "质量管理部" };

    expect(departmentMatchesKeyword(department, "质量管理")).toBe(true);
    expect(departmentMatchesKeyword(department, "质量")).toBe(true);
    expect(departmentMatchesKeyword(department, "设备")).toBe(false);
  });
});
