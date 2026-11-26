import { locationContext } from "@/contexts/locationContext";
import { fireEvent, render, screen, waitFor } from "@/test/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import Config from "./Config";
import {
  parseKunlianAutoOnboardingYaml,
  updateKunlianAutoOnboardingYaml,
} from "./kunlianConfigYaml";

const {
  mockGetSysConfigApi,
  mockSetSysConfigApi,
  mockShowApiError,
  mockToastShow,
  mockNotificationOpen,
} = vi.hoisted(() => ({
  mockGetSysConfigApi: vi.fn(),
  mockSetSysConfigApi: vi.fn(),
  mockShowApiError: vi.fn(),
  mockToastShow: vi.fn(),
  mockNotificationOpen: vi.fn(),
}));

vi.mock("../../../controllers/API/user", () => ({
  getSysConfigApi: mockGetSysConfigApi,
  setSysConfigApi: mockSetSysConfigApi,
}));

vi.mock("../../../controllers/request", () => ({
  showApiError: mockShowApiError,
}));

vi.mock("react-ace", () => ({
  default: function MockAceEditor({
    value,
    onChange,
  }: {
    value: string;
    onChange?: (val: string) => void;
  }) {
    return (
      <textarea
        data-testid="mock-ace-editor"
        value={value}
        onChange={(e) => onChange?.(e.target.value)}
      />
    );
  },
}));

vi.mock("@bisheng/ui", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@bisheng/ui")>();
  return {
    ...actual,
    toast: { show: mockToastShow },
    notification: { open: mockNotificationOpen },
  };
});

function renderConfig({
  kunlianSsoConfigured = true,
  kunlianAutoOnboardingDefault = true,
  reloadConfig = vi.fn(),
}: {
  kunlianSsoConfigured?: boolean;
  kunlianAutoOnboardingDefault?: boolean;
  reloadConfig?: () => void;
} = {}) {
  return {
    reloadConfig,
    ...render(
      <locationContext.Provider
        value={{
          current: ["sys"],
          setCurrent: vi.fn(),
          isStackedOpen: false,
          setIsStackedOpen: vi.fn(),
          showSideBar: false,
          setShowSideBar: vi.fn(),
          extraNavigation: { title: "" },
          setExtraNavigation: vi.fn(),
          extraComponent: <></>,
          setExtraComponent: vi.fn(),
          appConfig: {
            kunlianSsoConfigured,
            kunlianAutoOnboardingDefault,
            kunlianAutoOnboardingEnabled: kunlianAutoOnboardingDefault,
          },
          reloadConfig,
        }}
      >
        <Config />
      </locationContext.Provider>,
    ),
  };
}

describe("kunlianConfigYaml", () => {
  it("parses inherit, true, false, and inline comments", () => {
    expect(parseKunlianAutoOnboardingYaml("environment:\n  enable_register: true\n")).toBe("inherit");
    expect(
      parseKunlianAutoOnboardingYaml(
        "sso_sync:\n  kunlian:\n    auto_onboarding_enabled: null # inherit\n",
      ),
    ).toBe("inherit");
    expect(
      parseKunlianAutoOnboardingYaml(
        "sso_sync:\n  kunlian:\n    auto_onboarding_enabled: false # disabled\n",
      ),
    ).toBe(false);
    expect(
      parseKunlianAutoOnboardingYaml(
        "sso_sync:\n  kunlian:\n    auto_onboarding_enabled: true\n",
      ),
    ).toBe(true);
  });

  it("updates existing key inline while preserving comments and surrounding YAML", () => {
    const input = [
      "environment:",
      "  enable_register: false",
      "",
      "sso_sync:",
      "  kunlian:",
      "    # keep comment",
      "    auto_onboarding_enabled: null # inline note",
      "",
    ].join("\n");

    const updated = updateKunlianAutoOnboardingYaml(input, false);
    expect(updated).toContain("# keep comment");
    expect(updated).toContain("auto_onboarding_enabled: false # inline note");
    expect(parseKunlianAutoOnboardingYaml(updated)).toBe(false);
  });

  it("appends sso_sync.kunlian block when absent", () => {
    const updated = updateKunlianAutoOnboardingYaml("environment:\n  enable_register: false\n", true);
    expect(updated).toContain("sso_sync:\n  kunlian:\n    auto_onboarding_enabled: true");
    expect(parseKunlianAutoOnboardingYaml(updated)).toBe(true);
  });
});

describe("Config Kunlian Auto-Onboarding Switch", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("hides Kunlian onboarding card when kunlianSsoConfigured is false", async () => {
    mockGetSysConfigApi.mockResolvedValue("environment:\n  enable_register: false\n");
    renderConfig({ kunlianSsoConfigured: false });

    await waitFor(() => {
      expect(screen.getByTestId("mock-ace-editor")).toHaveValue("environment:\n  enable_register: false\n");
    });
    expect(screen.queryByRole("switch")).not.toBeInTheDocument();
  });

  it("toggles Switch immediately, updates YAML, calls setSysConfigApi and reloadConfig, and allows reset to inherit", async () => {
    const initialYaml = [
      "environment:",
      "  enable_register: false",
      "sso_sync:",
      "  kunlian:",
      "    auto_onboarding_enabled: null",
      "",
    ].join("\n");
    mockGetSysConfigApi.mockResolvedValue(initialYaml);
    mockSetSysConfigApi.mockResolvedValue({});
    const reloadConfig = vi.fn();

    renderConfig({ kunlianSsoConfigured: true, kunlianAutoOnboardingDefault: true, reloadConfig });

    const toggle = await screen.findByRole("switch");
    await waitFor(() => {
      expect(toggle).toBeEnabled();
      expect(toggle).toHaveAttribute("aria-checked", "true");
    });

    fireEvent.click(toggle);

    await waitFor(() => {
      expect(mockSetSysConfigApi).toHaveBeenCalledTimes(1);
    });
    const savedPayload = mockSetSysConfigApi.mock.calls[0][0] as { data: string };
    expect(parseKunlianAutoOnboardingYaml(savedPayload.data)).toBe(false);
    expect(screen.getByTestId("mock-ace-editor")).toHaveValue(savedPayload.data);
    await waitFor(() => {
      expect(reloadConfig).toHaveBeenCalledTimes(1);
    });
    expect(toggle).toHaveAttribute("aria-checked", "false");

    const resetBtn = screen.getByRole("button", { name: "system.kunlianAutoOnboarding.resetInherit" });
    fireEvent.click(resetBtn);

    await waitFor(() => {
      expect(mockSetSysConfigApi).toHaveBeenCalledTimes(2);
    });
    const resetPayload = mockSetSysConfigApi.mock.calls[1][0] as { data: string };
    expect(parseKunlianAutoOnboardingYaml(resetPayload.data)).toBe("inherit");
    expect(toggle).toHaveAttribute("aria-checked", "true");
  });

  it("syncs Switch state from inline YAML edits and rolls back on save failure", async () => {
    const initialYaml = "sso_sync:\n  kunlian:\n    auto_onboarding_enabled: true\n";
    mockGetSysConfigApi.mockResolvedValue(initialYaml);
    mockSetSysConfigApi.mockRejectedValue(new Error("save failed"));

    renderConfig({ kunlianSsoConfigured: true, kunlianAutoOnboardingDefault: true });

    const editor = await screen.findByTestId("mock-ace-editor");
    const toggle = screen.getByRole("switch");
    await waitFor(() => expect(toggle).toHaveAttribute("aria-checked", "true"));

    fireEvent.change(editor, {
      target: { value: "sso_sync:\n  kunlian:\n    auto_onboarding_enabled: false\n" },
    });
    expect(toggle).toHaveAttribute("aria-checked", "false");

    fireEvent.click(toggle);

    await waitFor(() => {
      expect(mockShowApiError).toHaveBeenCalledTimes(1);
    });
    expect(toggle).toHaveAttribute("aria-checked", "false");
    expect(editor).toHaveValue("sso_sync:\n  kunlian:\n    auto_onboarding_enabled: false\n");
  });
});
