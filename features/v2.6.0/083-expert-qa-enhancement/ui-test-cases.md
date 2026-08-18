# F083 专家问答 · UI 自动化测试用例（Playwright）

| 项 | 内容 |
|---|---|
| 作者视角 | 资深自动化测试工程师：稳定选择器、角色夹具、可失败即定位、不测实现细节 |
| 被测端 | Portal：`/expert-qa`、`/expert-qa/ask`、`/expert-qa/:id`、`/expert-qa/expertmanage` |
| 契约 | [`design.md`](./design.md) §2；页面只信 `display_status` + `capabilities` |
| 覆盖口径 | **UI 可测场景全集 41**；本 Feature **自动化 35 ≈ 85%**；其余 6 条走 API/定时/账号域，不硬塞 UI |
| 运行 | **默认无头 Playwright CLI**；排障/单步可用 **Playwright MCP**（`user-playwright`）。禁止默认 headed 窗口。需联调栈 `:5173` + BFF + BiSheng |

---

## 1. 策略（资深口径）

1. **测用户能看见和点到的行为**，不测 CSS 像素、不测内部 state。  
2. **选择器只用 `data-testid`**（见 §3）；禁止 `nth-child` / 中文 XPath 当主定位。  
3. **角色隔离**：每个 spec 独立登录态，禁止用例间共享 cookie。  
4. **数据前缀** `uitest-f083-`；`afterEach` 只清本前缀。  
5. **断言双层**：UI 文案 + 必要时拦截 API `status_code`（183xx）。  
6. **并发/时钟/销户** 不进 Playwright（不稳定）；对应 AC 由后端 pytest 覆盖。  
7. **失败即证据**：截图 + trace；通知/审批用例保留 HAR。  
8. **执行通道**：回归与 CI 只用无头 CLI；MCP 仅用于 Agent 复现单条失败，不断言替代 CLI 门禁。

### 角色夹具

| Fixture | 含义 |
|---------|------|
| `guest` | 未登录 |
| `userA` | 普通登录用户（提问者） |
| `userB` | 普通登录、非受邀 |
| `expertInvited` | 有效专家且被定向邀请 |
| `expertOther` | 有效专家、未被邀请 |
| `expertDisabled` | 已停用专家 |
| `expertAdmin` | 门户专家库管理员（非超管） |
| `superAdmin` | 平台超管 |

---

## 2. 覆盖矩阵（41 场景 → 85%）

| ID | 场景 | P | 层 | AC | 自动化 |
|----|------|---|----|----|--------|
| UI-01 | 未登录进列表/提问被拦 | P0 | Playwright | AC-41 | Y |
| UI-02 | 列表三态文案 | P0 | Playwright | AC-01, AC-37 | Y |
| UI-03 | 「未解决」= 未回答∪待采纳 | P0 | Playwright | AC-02 | Y |
| UI-04 | 「我的 / 邀请我的」不是待采纳 | P0 | Playwright | AC-03 | Y |
| UI-05 | 发布定向题（1–3 专家） | P0 | Playwright | AC-04 | Y |
| UI-06 | 发布公开题（0–3） | P0 | Playwright | AC-05 | Y |
| UI-07 | 无权用户打定向深链 | P0 | Playwright | AC-06 | Y |
| UI-08 | 定向不出现在无权者列表/搜索 | P0 | Playwright | AC-04, AC-06 | Y |
| UI-09 | 类似问题不阻断发布 | P1 | Playwright | AC-42 | Y |
| UI-10 | 关联文档无权：正文在、链接不可用；文案不是「文档不存在」 | P1 | Playwright | AC-08, AC-48 | Y |
| UI-41 | 关联文档有权：选择后打开成功、标题正确 | P0 | Playwright | AC-47 | Y |
| UI-11 | 首答后面板锁定 | P0 | Playwright | AC-09 | Y |
| UI-12 | 删光未采纳回答后锁仍在 | P0 | Playwright | AC-11 | Y |
| UI-13 | 定向非受邀无回答框 | P0 | Playwright | AC-12 | Y |
| UI-14 | 公开首次采纳前受邀外专家可答 | P0 | Playwright | AC-13 | Y |
| UI-15 | 公开首次采纳后无资格专家无回答框 | P0 | Playwright | AC-14 | Y |
| UI-16 | 停用专家无回答入口 | P0 | Playwright | AC-15 | Y |
| UI-17 | 定向未答不可评论 | P0 | Playwright | AC-43 | Y |
| UI-18 | 定向已答可评论 | P1 | Playwright | AC-44 | Y |
| UI-19 | 公开/转公开后登录用户可评 | P1 | Playwright | AC-45 | Y |
| UI-20 | 提问者采纳→已解决 | P0 | Playwright | AC-16 | Y |
| UI-21 | 第 4 次采纳失败提示 | P0 | Playwright | AC-17 | Y |
| UI-22 | 同专家多答可分别采纳（UI 槽位） | P1 | Playwright | AC-18 | Y |
| UI-23 | 非管理员只见匿名别名 | P0 | Playwright | AC-19 | Y |
| UI-24 | 同用户同题别名不因删内容重排 | P1 | Playwright | AC-20 | Y |
| UI-25 | 专家库管理员破匿名 | P0 | Playwright | AC-21 | Y |
| UI-26 | 转公开后按预选项展示身份、不再询问 | P0 | Playwright | AC-22 | Y |
| UI-27 | 已解决定向发起转公开（1/3/7） | P0 | Playwright | AC-23 | Y |
| UI-28 | 审批拒绝后保持定向可重发 | P0 | Playwright | AC-24 | Y |
| UI-29 | 全体同意后不可逆公开 | P0 | Playwright | AC-24, AC-28 | Y |
| UI-30 | 转公开后非原受邀无回答框 | P0 | Playwright | AC-28 | Y |
| UI-31 | 审批中无删答按钮 | P1 | Playwright | PRD 删答锁定 | Y |
| UI-32 | 专家库停用/恢复 | P0 | Playwright | AC-29, AC-31 | Y |
| UI-33 | 非管理员无专家库写按钮 | P0 | Playwright | AC-30 | Y |
| UI-34 | 超管可见违规删除；专家库管理员不可见 | P0 | Playwright | AC-32, AC-33 | Y |
| UI-35 | 邀请/采纳/转公开通知可点进且再鉴权 | P1 | Playwright | AC-36 | Y |
| UI-36 | 非法有效期控件不可提交 | P1 | Playwright | AC-23 | Y |
| UI-37 | 并发双首答 | P2 | **pytest** | AC-10 | N（UI 不测竞态） |
| UI-38 | 审批到期自动过期 | P2 | **pytest+Beat** | AC-26 | N（时钟） |
| UI-39 | 提问者账号停用结束审批 | P2 | **pytest** | AC-27, AC-34 | N（账号域） |
| UI-40 | 审批中停用专家默认同意 | P2 | **pytest** | AC-25, AC-35, AC-46 | N（审计+重判） |

**计算**：自动化 UI 场景 35 / 全集 41 ≈ **85.4%**。  
反向 AC-37 含在 UI-02；AC-38/39/40 非页面流程，由后端测试覆盖，不计入 UI 全集。

---

## 3. `data-testid` 约定（实现任务必须挂上）

| testid | 页面 |
|--------|------|
| `eqa-list` / `eqa-status-filter` / `eqa-filter-mine` / `eqa-filter-invited` | 列表 |
| `eqa-card` / `eqa-card-status` / `eqa-card-type` | 卡片 |
| `eqa-ask-form` / `eqa-type-directed` / `eqa-type-public` | 提问 |
| `eqa-invite-picker` / `eqa-similar-list` / `eqa-submit-question` | 提问 |
| `eqa-detail` / `eqa-answer-form` / `eqa-adopt` / `eqa-comment-form` | 详情 |
| `eqa-lock-banner` / `eqa-edit-question` / `eqa-delete-question` | 锁定 |
| `eqa-identity` / `eqa-real-identity` | 匿名/破匿名 |
| `eqa-related-doc` / `eqa-related-doc-blocked` | 文档 |
| `eqa-publish-start` / `eqa-publish-duration` / `eqa-publish-approve` / `eqa-publish-reject` | 转公开 |
| `eqa-expert-disable` / `eqa-expert-enable` | 专家库 |
| `eqa-moderate-delete` | 违规删除 |
| `eqa-denied` | 无权限 |

---

## 4. 详细用例（P0 全写步骤；P1 同结构压缩）

### UI-01 未登录拦截

- **前置**：清 cookie。  
- **步骤**：打开 `/expert-qa`、`/expert-qa/ask`。  
- **期望**：跳转登录；无问题卡片、无发布表单。  
- **失败定位**：登录墙未挂 / 列表接口未 401。

### UI-02 三态文案

- **数据**：三题：0 答；有答未采纳；已采纳。  
- **期望**：`eqa-card-status` 分别为 `未回答` / `待采纳` / `已解决`；页面无「已关闭」。

### UI-03 未解决筛选

- **步骤**：筛「未解决」。  
- **期望**：只含未回答+待采纳；已解决不出现。

### UI-04 我的 / 邀请我的

- **步骤**：切「我提问的」「邀请我的」。  
- **期望**：请求 `filter=mine|invited_me`，**不得**带业务态 `status=3/4`；文案不是「待采纳」。

### UI-05 发布定向

- **步骤**：`userA` 选定向，邀 1 位 `expertInvited`，必填「转公开后是否公开姓名」，提交。  
- **期望**：进详情 `eqa-card-type=定向`；`userB` 列表不可见。  
- **反向**：邀 0 人提交 → 校验错误不发请求。

### UI-06 发布公开

- **步骤**：公开、可不邀专家、选是否匿名。  
- **期望**：`userB` 列表可见完整标题。

### UI-07 / UI-08 定向隔离

- **步骤**：`userB` 打开 `/expert-qa/{directedId}`；列表搜索标题关键字。  
- **期望**：`eqa-denied`；搜索无该标题（防泄露）。

### UI-10 关联文档无权

- **前置**：公开题关联一篇 `userB` 无权限的知识库文档；`userB` 登录。  
- **步骤**：打开 `/expert-qa/{id}`。  
- **期望**：`eqa-detail` 正文可见；`eqa-related-doc-blocked` 存在且不可打开；页面**无**「文档不存在」。  
- **失败定位**：详情把无权当成删除 / 问答正文被挡住。

### UI-41 关联文档有权打开

- **前置**：`userA` 对某知识库文档有权；提问时从选择器勾选该文档。  
- **步骤**：提交后进详情，点击 `eqa-related-doc`。  
- **期望**：打开 `/space/{spaceId}/file/{fileId}`；标题与选择器一致；可预览；**不得**显示「文档不存在」。选择器列出的 `fileId` 与打开 URL 同一 ID。  
- **失败定位**：picker 仍走 legacy children、详情走 F059 durable，id 对不上。

### UI-11 / UI-12 锁定

- **步骤**：受邀专家首答 → 提问者详情无 `eqa-edit-question` / `eqa-delete-question`，有 `eqa-lock-banner`。专家删唯一未采纳答。  
- **期望**：状态可回「未回答」；编辑/删除仍不可用。

### UI-13～16 回答资格

- 定向+`expertOther`：无 `eqa-answer-form`。  
- 公开未采纳+`expertOther`：有表单且可提交。  
- 公开已首次采纳、该专家不在快照：无表单。  
- `expertDisabled`：无表单。

### UI-17～19 评论

- 定向未答：`eqa-comment-form` 不出现或提交 18309。  
- 定向已答：可评。  
- 公开：`userB` 可评。

### UI-20 / UI-21 采纳

- 提问者点 `eqa-adopt` → 状态「已解决」。  
- 已 3 条采纳后再点 → toast/错误 18304；前 3 条仍为已采纳。

### UI-23 / UI-25 匿名

- 公开匿名提问：`userB` 只见 `eqa-identity` 别名，无 `eqa-real-identity`。  
- `expertAdmin` 同页可见真名。

### UI-27～30 转公开

- 已解决定向：发起人可选 1/3/7 天；发起人自动同意。  
- 另一审批人拒绝 → 仍定向，可再发起。  
- 全体同意 → 类型变公开；身份按预选项；无二次询问弹窗。  
- `expertOther` 仍无回答框。

### UI-32～34 管理入口

- `expertAdmin`：停用后邀请列表不可选该专家。  
- `userA`：`/expert-qa/expertmanage` 无停用按钮。  
- `superAdmin` 详情有 `eqa-moderate-delete`；`expertAdmin` 无。

### UI-35 通知再鉴权

- 受邀通知点进可见；`userB` 持同一通知 URL → `eqa-denied`。

---

## 5. Playwright 样例（可直接落 `e2e/`）

### 5.1 夹具片段

```ts
// e2e/expert-qa/fixtures.ts
import { test as base, expect } from '@playwright/test';

export const test = base.extend<{
  userA: { page: import('@playwright/test').Page };
}>({
  userA: async ({ browser }, use) => {
    const ctx = await browser.newContext({ storageState: 'e2e/.auth/userA.json' });
    const page = await ctx.newPage();
    await use({ page });
    await ctx.close();
  },
});

export { expect };
```

### 5.2 UI-05 发布定向（完整样例）

```ts
// e2e/expert-qa/ask-directed.spec.ts
import { test, expect } from './fixtures';

test.describe('UI-05 发布定向提问', () => {
  test('邀 1 位专家后提交，无权用户不可见标题', async ({ userA, browser }) => {
    const { page } = userA;
    await page.goto('/expert-qa/ask');
    await page.getByTestId('eqa-type-directed').click();
    await page.getByTestId('eqa-ask-form').getByLabel('标题').fill('uitest-f083-定向振动');
    await page.getByTestId('eqa-ask-form').getByLabel('问题描述').fill('现象与已做检查');
    await page.getByTestId('eqa-invite-picker').click();
    await page.getByRole('option').first().click();
    await page.getByLabel('转公开后是否公开姓名').click();
    await page.getByTestId('eqa-submit-question').click();
    await expect(page.getByTestId('eqa-detail')).toBeVisible();
    await expect(page.getByTestId('eqa-card-type')).toHaveText(/定向/);

    const other = await browser.newContext({ storageState: 'e2e/.auth/userB.json' });
    const otherPage = await other.newPage();
    await otherPage.goto('/expert-qa');
    await expect(otherPage.getByText('uitest-f083-定向振动')).toHaveCount(0);
    await other.close();
  });

  test('定向未邀专家时不能提交', async ({ userA }) => {
    const { page } = userA;
    await page.goto('/expert-qa/ask');
    await page.getByTestId('eqa-type-directed').click();
    await page.getByTestId('eqa-submit-question').click();
    await expect(page.getByTestId('eqa-detail')).toHaveCount(0);
    await expect(page.getByTestId('eqa-ask-form')).toBeVisible();
  });
});
```

### 5.3 UI-07 定向深链

```ts
// e2e/expert-qa/directed-access.spec.ts
import { test, expect } from './fixtures';

test('UI-07 无权用户打开定向详情见无权限而非标题', async ({ browser }) => {
  const ctx = await browser.newContext({ storageState: 'e2e/.auth/userB.json' });
  const page = await ctx.newPage();
  await page.goto('/expert-qa/SEED_DIRECTED_ID');
  await expect(page.getByTestId('eqa-denied')).toBeVisible();
  await expect(page.getByTestId('eqa-detail')).toHaveCount(0);
  await ctx.close();
});
```

### 5.4 UI-20 采纳

```ts
// e2e/expert-qa/adopt.spec.ts
import { test, expect } from './fixtures';

test('UI-20 提问者采纳后状态变为已解决', async ({ userA }) => {
  const { page } = userA;
  await page.goto('/expert-qa/SEED_PENDING_ADOPT_ID');
  await page.getByTestId('eqa-adopt').first().click();
  await expect(page.getByTestId('eqa-card-status')).toHaveText(/已解决/);
});
```

---

## 6. 如何执行（无头 CLI / MCP）

### 6.1 默认：无头 Playwright CLI（回归与 CI 唯一门禁）

```bash
cd shougang-group-knowledge-portal/frontend
# 默认 headless=true，不要加 --headed
npx playwright test e2e/expert-qa --project=chromium
npx playwright test e2e/expert-qa --grep @p0
npx playwright test e2e/expert-qa/ask-directed.spec.ts --reporter=line
```

`playwright.config.ts` 必须：`use.headless: true`；CI 环境变量 `CI=true` 时禁止 headed。本地排障可用 `PWDEBUG=1`（仍无窗口优先）或仅在明确需要时 `--headed`。

### 6.2 可选：Playwright MCP（Agent 单步，不替代门禁）

Cursor 已接 `user-playwright` MCP。Agent 执行单条 UI 用例时：

1. `browser_navigate` 打开 `http://127.0.0.1:5173/expert-qa…`
2. `browser_snapshot` / `browser_find` 定位 `data-testid`
3. `browser_click` / `browser_type` / `browser_fill_form` 操作
4. 断言失败时 `browser_take_screenshot` + `browser_console_messages`
5. 结束 `browser_close`

约束：MCP **不跑** 35 条全量（会话长、无 JUnit 报告）；全量仍走 §6.1。MCP 与 CLI 共用同一套 testid 与角色账号。

### 6.3 稳定性与 CI

- `storageState` 按角色预登录，禁止每个 case 走 SSO。  
- 列表用 `eqa-card` + 标题精确匹配，禁止 `getByText` 模糊匹配公共词「已解决」。  
- 转公开/通知用例 `test.describe.serial` 仅限同一业务链；默认并行。  
- CI：无头 `playwright test --grep @p0` 必跑；P1 可 nightly。  
- flake 处理：重试最多 1 次且必须修根因（等待用 `expect` 自动重试，禁止死 `waitForTimeout`）。

## 7. 本 Feature 不测（明确）

- 专家分公式数值（AC-39）  
- 账号硬删（AC-38）  
- 积分账本流水（F070）  
- 视觉回归/像素
