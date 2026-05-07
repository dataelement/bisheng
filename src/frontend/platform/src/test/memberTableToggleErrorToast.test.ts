import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

/**
 * Regression: 子租户管理员在「组织与成员 → 启用/禁用账号」切换 Switch 时，
 * 后端 envelope 返回 ``status_code: 500``（"Quit that! You don't have rights..."）
 * 但页面只看到一个空白的成功 toast。
 *
 * 根因：``captureAndAlertRequestErrorHoc`` 错误路径返回 ``false``（非 ``null``），
 * 旧逻辑 ``if (res === null) loadMembers() else toast(success)`` 永远走 else 分支，
 * 把 HoC 已经弹出的红色错误 toast 立即被一个空白 success toast 顶掉
 * （TOAST_LIMIT=1）。修复：成功侧改写在 API ``.then`` 内，HoC 外仅根据
 * ``res === false`` 触发回滚，避免和 HoC 的错误弹窗打架。
 */

const MEMBER_TABLE_PATH = resolve(
  __dirname,
  "../pages/DepartmentPage/components/MemberTable.tsx",
);

function readSource(): string {
  return readFileSync(MEMBER_TABLE_PATH, "utf-8");
}

describe("MemberTable enable/disable toggle (regression)", () => {
  it("does not gate success toast on res === null (HoC returns false on error)", () => {
    const src = readSource();
    // The buggy branch was: `if (res === null) { loadMembers() } else { ...success toast }`.
    // The fix moves the success toast inside the API .then() and uses
    // `if (res === false) loadMembers()` for the revert path.
    expect(src).not.toMatch(/if\s*\(\s*res\s*===\s*null\s*\)\s*\{\s*loadMembers\(\)/);
  });

  it("checks res === false to trigger optimistic-update revert", () => {
    const src = readSource();
    expect(src).toMatch(/res\s*===\s*false/);
  });

  it("fires the success toast inside the API .then(), not after the HoC", () => {
    const src = readSource();
    // The handler should pipe success toast/onChanged through disableUserApi(...).then(...)
    // so that on rejection the toast is never reached and HoC's error toast survives.
    expect(src).toMatch(
      /disableUserApi\([^)]*\)\.then\(\s*\(\s*\)\s*=>\s*\{[\s\S]*toast\(\s*\{\s*title:[^}]*variant:\s*"success"/,
    );
  });
});
