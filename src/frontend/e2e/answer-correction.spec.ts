import { expect, test, type Browser } from "@playwright/test";

interface Fixture {
    actors: Record<"user" | "owner" | "maintainer", { Cookie: string }>;
    quote: string;
    knowledge_id: number;
    assignee_id: number;
}

const raw = process.env.BISHENG_CORRECTION_SCENARIO;
const chatUrl = process.env.BISHENG_CORRECTION_CHAT_URL;
const queueUrl = process.env.BISHENG_CORRECTION_QUEUE_URL;

async function actorPage(browser: Browser, fixture: Fixture, actor: keyof Fixture["actors"], url: string) {
    const context = await browser.newContext({ locale: "en-US" });
    const value = fixture.actors[actor].Cookie.replace(/^access_token_cookie=/, "");
    await context.addCookies([{ name: "access_token_cookie", value, domain: new URL(url).hostname, path: "/" }]);
    const page = await context.newPage();
    await page.goto(url);
    return page;
}

test("UI-119-01 submits feedback, assigns a maintainer, and displays the reply", async ({ browser }) => {
    test.skip(!raw || !chatUrl || !queueUrl, "Requires the live feedback fixture and both frontend URLs");
    const fixture: Fixture = JSON.parse(raw!);
    const user = await actorPage(browser, fixture, "user", chatUrl!);
    const owner = await actorPage(browser, fixture, "owner", queueUrl!);
    const maintainer = await actorPage(browser, fixture, "maintainer", queueUrl!);
    const correction = `Browser correction ${Date.now()}`;
    const reply = `Resolved ${correction}`;
    try {
        const report = user.getByRole("button", { name: "Report an error" });
        await report.hover();
        await report.click();
        await user.getByLabel("Original sentence").fill(fixture.quote);
        await user.getByLabel("Correction", { exact: true }).fill(correction);
        await user.getByLabel("Supporting evidence").fill("Verified source https://example.org/reference");
        await user.getByRole("button", { name: "Submit", exact: true }).click();
        await expect(user.getByRole("dialog")).toBeHidden();

        await owner.reload();
        await owner.getByRole("listitem").filter({ hasText: "Awaiting assignment" })
            .getByRole("button", { name: "View" }).first().click();
        await expect(owner.getByRole("dialog")).toContainText(correction);
        await owner.getByLabel("Knowledge base").selectOption(String(fixture.knowledge_id));
        await owner.getByLabel("Maintainer").selectOption(String(fixture.assignee_id));
        await owner.getByRole("button", { name: "Assign", exact: true }).click();
        await expect(owner.getByRole("dialog")).toBeHidden();

        await maintainer.getByRole("button", { name: "Assigned to me" }).click();
        await maintainer.getByRole("listitem").filter({ hasText: "In progress" })
            .getByRole("button", { name: "View" }).first().click();
        await expect(maintainer.getByRole("dialog")).toContainText(correction);
        await maintainer.getByLabel("Processing result").fill("Corrected the source document.");
        await maintainer.getByRole("button", { name: "Save", exact: true }).click();
        await expect(maintainer.getByRole("dialog")).toBeHidden();

        await owner.reload();
        await owner.getByRole("listitem").filter({ hasText: "Awaiting reply" })
            .getByRole("button", { name: "View" }).first().click();
        await owner.getByLabel("Reply", { exact: true }).fill(reply);
        await owner.getByRole("button", { name: "Send", exact: true }).click();
        await expect(owner.getByRole("dialog")).toBeHidden();

        await user.getByRole("button", { name: "My feedback" }).click();
        await expect(user.getByRole("dialog")).toContainText(reply);
    } finally {
        await Promise.all([user.context().close(), owner.context().close(), maintainer.context().close()]);
    }
});

test("UI-119-02 hides reporting on an answer from an app without a knowledge base", async ({ browser }) => {
    const unsupportedUrl = process.env.BISHENG_CORRECTION_UNSUPPORTED_CHAT_URL;
    test.skip(!raw || !unsupportedUrl, "Requires the live feedback fixture and the unsupported chat URL");
    const fixture: Fixture = JSON.parse(raw!);
    const user = await actorPage(browser, fixture, "user", unsupportedUrl!);
    try {
        const eligibility = user.waitForResponse((response) =>
            response.url().includes("/answer-corrections/eligibility/") && response.ok());
        await user.reload();
        await eligibility;
        await expect(user.getByText(fixture.quote, { exact: true })).toBeVisible();
        await expect(user.getByRole("button", { name: "My feedback" })).toBeVisible();
        await expect(user.getByRole("button", { name: "Report an error" })).toHaveCount(0);
    } finally {
        await user.context().close();
    }
});
