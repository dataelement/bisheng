import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { createInstance } from "i18next";
import { I18nextProvider, initReactI18next } from "react-i18next";
import { afterEach, expect, it, vi } from "vitest";
import en from "../../../../public/locales/en-US/model.json";
import ja from "../../../../public/locales/ja/model.json";
import zh from "../../../../public/locales/zh-Hans/model.json";
import { ModelRemovalDialog } from "./ModelRemovalDialog";
import type { ModelRemovalView } from "./useModelRemoval";

vi.unmock("react-i18next");
afterEach(cleanup);

it.each([
  ["en-US", en],
  ["zh-Hans", zh],
  ["ja", ja],
] as const)(
  "shows qualified names and real links, and only counts restricted sources in %s",
  async (language, copy) => {
    const i18n = createInstance();
    await i18n
      .use(initReactI18next)
      .init({
        lng: language,
        resources: { [language]: { model: copy } },
        interpolation: { escapeValue: false },
      });
    const state: ModelRemovalView = {
      kind: "delete",
      pending: false,
      needsRefresh: false,
      dispatched: false,
      force: null,
      result: {
        inspection: {
          server_id: 7,
          targets: [],
          blocked: true,
          check_complete: true,
          source_counts: [["assistant", 4]],
          slot_counts: [["assistant", 4]],
          qualified_counts: [["assistant", 2]],
          restricted_counts: [["assistant", 2]],
          source_page: {
            data: [],
            page_size: 50,
            has_more: false,
            next_cursor: null,
          },
        },
        confirmation: {
          operation: "model_delete_server",
          confirmation_id: "real-plan",
          plan_digest: "a".repeat(64),
          expires_at: "2099-01-01",
        },
      },
      page: {
        data: [
          {
            disclosure: {
              source: {
                source_type: "assistant",
                tenant_id: 101,
                source_id: "qualified-id-not-a-label",
                source_version: "current",
              },
              name: "Visible assistant",
              version_label: "v1",
              entry: "/assistant/qualified",
            },
            matched_slot_count: 1,
          },
          {
            disclosure: {
              source: {
                source_type: "assistant",
                tenant_id: 101,
                source_id: "no-entry-id-not-a-label",
                source_version: "current",
              },
              name: "Visible without entry",
              version_label: null,
              entry: null,
            },
            matched_slot_count: 1,
          },
        ],
        page_size: 50,
        has_more: false,
        next_cursor: null,
      },
    };
    render(
      <I18nextProvider i18n={i18n}>
        <ModelRemovalDialog
          view={state}
          onCancel={vi.fn()}
          onConfirm={vi.fn()}
          onForce={vi.fn()}
          onRefresh={vi.fn()}
          onLoadMore={vi.fn()}
        />
      </I18nextProvider>,
    );
    expect(
      screen.getByRole("link", { name: "Visible assistant" }),
    ).toHaveAttribute("href", "/assistant/qualified");
    expect(screen.getByText("Visible without entry").closest("a")).toBeNull();
    expect(
      screen.getByText(
        i18n.t("model.removalRestrictedCount", { ns: "model", count: 2 }),
      ),
    ).toBeVisible();
    expect(document.body).not.toHaveTextContent("qualified-id-not-a-label");
    expect(document.body).not.toHaveTextContent("no-entry-id-not-a-label");
    expect(
      screen.getByRole("button", {
        name: i18n.t("model.removalConfirmDelete", { ns: "model" }),
      }),
    ).toBeDisabled();
  },
);
