import { act, render, screen } from "@testing-library/react";
import i18next from "i18next";
import { I18nextProvider } from "react-i18next";
import en from "~/locales/en/translation.json";
import zh from "~/locales/zh-Hans/translation.json";
import ja from "~/locales/ja/translation.json";
import { PermissionDraftEditor } from "./PermissionDraftEditor";
import { permissionModelLabel } from "./permissionModelLabel";

jest.mock("~/hooks", () => ({
  useLocalize: () => jest.requireActual("react-i18next").useTranslation().t,
}));

const resources = {
  en: { translation: en },
  "zh-Hans": { translation: zh },
  ja: { translation: ja },
};

async function createLocale(language: string) {
  const locale = i18next.createInstance();
  await locale.init({ lng: language, fallbackLng: "en", resources });
  return locale;
}

describe("permission model display names", () => {
  it.each(["en", "zh-Hans", "ja"] as const)("localizes standard keys in %s", async (language) => {
    const locale = await createLocale(language);
    for (const key of ["owner", "manager", "editor", "viewer"] as const) {
      expect(permissionModelLabel(key, "server label", locale.t))
        .toBe(resources[language].translation.com_permission[`level_${key}`]);
    }
  });

  it("preserves custom names and unknown keys", async () => {
    const locale = await createLocale("en");
    expect(permissionModelLabel("custom_owner", "Research lead", locale.t)).toBe("Research lead");
    expect(permissionModelLabel("custom_viewer", "Owner", locale.t)).toBe("Owner");
    expect(permissionModelLabel("future_role", undefined, locale.t)).toBe("future_role");
  });

  it("updates the protected creator row when the active language changes", async () => {
    const locale = await createLocale("en");
    const onChange = jest.fn();
    const rows = [{
      subjectType: "user" as const,
      subjectId: 1,
      subjectName: "Creator account",
      modelKey: "owner",
      modelName: zh.com_permission.level_owner,
      modelLevel: 4,
      protected: true,
    }];
    const options = [{ id: "owner", name: zh.com_permission.level_owner, level: 4 }];
    const view = (relationModels = options) => (
      <I18nextProvider i18n={locale}>
        <PermissionDraftEditor value={rows} onChange={onChange}
          capabilities={{ canChangeRelation: true, canRemove: true, relationModels }} />
      </I18nextProvider>
    );
    const { rerender } = render(view());
    expect(screen.getByText("Owner")).toBeInTheDocument();
    await act(async () => { await locale.changeLanguage("zh-Hans"); });
    expect(screen.getByText(zh.com_permission.level_owner)).toBeInTheDocument();
    await act(async () => { await locale.changeLanguage("en"); });
    expect(screen.getByText("Owner")).toBeInTheDocument();
    rerender(view([]));
    expect(screen.getByText("Owner")).toBeInTheDocument();
    expect(onChange).toHaveBeenCalledTimes(0);
    expect(rows[0].modelKey).toBe("owner");
  });
});
