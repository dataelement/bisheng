import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createInstance } from "i18next";
import type { ButtonHTMLAttributes, ReactNode } from "react";
import {
  deletePersonalTokenApi, getPersonalTokenStatusApi, issuePersonalTokenApi,
  type PersonalTokenItem, type PersonalTokenStatus,
} from "~/api/personalToken";
import en from "~/locales/en/translation.json";
import zh from "~/locales/zh-Hans/translation.json";
import ja from "~/locales/ja/translation.json";
import { copyText } from "~/utils";
import { PersonalTokenDialog } from "./PersonalTokenDialog";

const mockI18n = createInstance();
const mockToast = jest.fn();
const mockConfirm = jest.fn();
jest.mock("~/hooks", () => ({ useLocalize: () => mockI18n.t.bind(mockI18n) }));
jest.mock("~/Providers/ToastContext", () => ({ useToastContext: () => ({ showToast: mockToast }) }));
jest.mock("~/Providers/ConfirmContext", () => ({ useConfirm: () => mockConfirm }));
jest.mock("~/utils", () => ({ copyText: jest.fn(), cn: (...parts: string[]) => parts.filter(Boolean).join(" ") }));
jest.mock("bisheng-icons", () => ({ Outlined: { Send: () => null, Close: () => null, Copy: () => null } }));
jest.mock("~/api/personalToken", () => ({
  ...jest.requireActual("~/api/personalToken"),
  getPersonalTokenStatusApi: jest.fn(), issuePersonalTokenApi: jest.fn(), deletePersonalTokenApi: jest.fn(),
}));
jest.mock("~/api/request", () => ({ __esModule: true, default: {} }));
jest.mock("~/components/ui", () => ({
  ...jest.requireActual("~/components/ui/Dialog"),
  // eslint-disable-next-line @typescript-eslint/no-require-imports -- jest.mock factories cannot close over imports
  Button: require("react").forwardRef(({ children, disabled, onClick, loading, "aria-label": label }:
    ButtonHTMLAttributes<HTMLButtonElement> & {
      color?: string; variant?: string; size?: string; iconOnly?: boolean; loading?: boolean;
    }, ref: React.Ref<HTMLButtonElement>) => (
    <button ref={ref} disabled={disabled || loading} onClick={onClick} aria-label={label}>{children}</button>
  )),
  Checkbox: ({ checked, onCheckedChange }: { checked: boolean; onCheckedChange: (value: boolean) => void }) => (
    <input type="checkbox" checked={checked} onChange={(event) => onCheckedChange(event.target.checked)} />
  ),
  TooltipAnchor: ({ children }: { children: ReactNode }) => <span>{children}</span>,
}));

const token: PersonalTokenItem = {
  id: 1, name: "Personal access token", key_mask: "bs-pat-****abcd",
  scopes: ["knowledge:read"], expires_at: "2027-09-11T16:00:00",
  revoked_at: null, last_used_at: null, is_valid: true, create_time: "2026-09-11T16:00:00",
};
const plaintext = "test-issued-credential";

function statusOf(overrides: Partial<PersonalTokenStatus> = {}): PersonalTokenStatus {
  return { enabled: true, token: null, holder_is_admin: false, data_scope: "all_visible", ttl_days: 30, ...overrides };
}

function findRevealDialog() {
  return screen.findByRole("dialog", { name: mockI18n.t("com_ai_access.reveal_title") });
}

beforeAll(async () => {
  await mockI18n.init({
    lng: "en", fallbackLng: "en",
    // Mirror the app's brand interpolation so $t(bisheng) resolves in copy.
    interpolation: { escapeValue: false, defaultVariables: { bisheng: "BISHENG", bishengZh: "BISHENG" } },
    resources: { en: { translation: en }, "zh-Hans": { translation: zh }, ja: { translation: ja } },
  });
});
beforeEach(async () => {
  await mockI18n.changeLanguage("en");
  jest.mocked(getPersonalTokenStatusApi).mockResolvedValue(statusOf());
  jest.mocked(issuePersonalTokenApi).mockResolvedValue({ ...token, plaintext, holder_is_admin: false });
  jest.mocked(deletePersonalTokenApi).mockResolvedValue({ revoked: 1 });
  jest.mocked(copyText).mockResolvedValue();
  mockConfirm.mockResolvedValue(true);
});

it.each(["en", "zh-Hans", "ja"])("copies the visible prompt in %s with the current instance URLs", async (language) => {
  await mockI18n.changeLanguage(language);
  render(<PersonalTokenDialog open onOpenChange={jest.fn()} />);
  await waitFor(() => expect(screen.getByRole("button", { name: mockI18n.t("com_ai_access.get_key") })).toBeEnabled());
  const prompt = mockI18n.t("com_ai_access.install_prompt", {
    skillPackUrl: "http://localhost:3080/api/v1/open-api/skill-packs/knowledge-search",
    tokenPageUrl: "http://localhost:3080/workspace/settings/ai-access?connect=1",
  });
  expect(screen.getByText(prompt, { normalizer: (value) => value })).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: mockI18n.t("com_ai_access.copy_all") }));
  expect(copyText).toHaveBeenCalledWith(prompt);
});

it("reveals the issued key in a stacked dialog and masks it once dismissed", async () => {
  const onOpenChange = jest.fn();
  render(<PersonalTokenDialog open onOpenChange={onOpenChange} />);
  await waitFor(() => expect(screen.getByRole("button", { name: "Generate my key" })).toBeEnabled());
  await userEvent.click(screen.getByRole("button", { name: "Generate my key" }));

  // The plaintext lives only inside the stacked reveal dialog; no save gate.
  const reveal = await findRevealDialog();
  expect(within(reveal).getByText(plaintext)).toBeInTheDocument();
  expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  await userEvent.click(within(reveal).getByRole("button", { name: "Copy API Key" }));
  expect(copyText).toHaveBeenCalledWith(plaintext);

  // Esc dismisses only the reveal dialog; the main dialog stays open and
  // immediately shows the masked item without a refetch.
  await userEvent.keyboard("{Escape}");
  await waitFor(() => expect(screen.queryByText(plaintext)).not.toBeInTheDocument());
  expect(onOpenChange).not.toHaveBeenCalled();
  expect(screen.getByText(token.key_mask)).toBeInTheDocument();
  expect(screen.getByText("Status: Valid")).toBeInTheDocument();
  expect(screen.getByText("Expires on: 2027-09-11")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Copy API Key" })).not.toBeInTheDocument();

  // With the gate gone, the main dialog closes freely.
  await userEvent.click(screen.getByRole("button", { name: "Close" }));
  expect(onOpenChange).toHaveBeenCalledWith(false);
});

it("bundles the key into the send-to-assistant copy action", async () => {
  render(<PersonalTokenDialog open onOpenChange={jest.fn()} />);
  await userEvent.click(await screen.findByRole("button", { name: "Generate my key" }));
  const reveal = await findRevealDialog();
  await userEvent.click(within(reveal).getByRole("button", { name: mockI18n.t("com_ai_access.copy_send_all") }));
  expect(copyText).toHaveBeenCalledWith(mockI18n.t("com_ai_access.copy_send_all_body", { key: plaintext }));
});

it("can regenerate a key and return to the empty card after deletion", async () => {
  jest.mocked(getPersonalTokenStatusApi).mockResolvedValue(statusOf({ token }));
  render(<PersonalTokenDialog open onOpenChange={jest.fn()} />);
  await userEvent.click(await screen.findByRole("button", { name: "Get a new key" }));
  await findRevealDialog();
  await userEvent.keyboard("{Escape}");
  await waitFor(() => expect(screen.queryByText(plaintext)).not.toBeInTheDocument());
  await userEvent.click(screen.getByRole("button", { name: "Delete key" }));
  await waitFor(() => expect(deletePersonalTokenApi).toHaveBeenCalledTimes(1));
  expect(screen.getByRole("button", { name: "Generate my key" })).toBeEnabled();
});

it("gates an administrator issuance behind the acknowledge step", async () => {
  jest.mocked(getPersonalTokenStatusApi).mockResolvedValue(statusOf({ holder_is_admin: true, ttl_days: 7 }));
  jest.mocked(issuePersonalTokenApi).mockResolvedValue({ ...token, plaintext, holder_is_admin: true });
  render(<PersonalTokenDialog open onOpenChange={jest.fn()} />);

  // The wide-scope admin banner carries the effective (capped) lifetime.
  expect(await screen.findByText(mockI18n.t("com_ai_access.admin_banner", { days: "7" }))).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Generate my key" }));

  expect(issuePersonalTokenApi).not.toHaveBeenCalled();
  expect(screen.getByText(mockI18n.t("com_ai_access.admin_confirm_title"))).toBeInTheDocument();
  const generate = screen.getByRole("button", { name: mockI18n.t("com_ai_access.admin_confirm_ok") });
  expect(generate).toBeDisabled();
  await userEvent.click(screen.getByRole("checkbox"));
  await userEvent.click(generate);
  await waitFor(() => expect(issuePersonalTokenApi).toHaveBeenCalledTimes(1));
  const reveal = await findRevealDialog();
  expect(within(reveal).getByText(plaintext)).toBeInTheDocument();
});

it("skips the admin ceremony and shows the narrowed scope once the tenant restricted retrieval", async () => {
  jest.mocked(getPersonalTokenStatusApi).mockResolvedValue(
    statusOf({ holder_is_admin: true, data_scope: "personal_only" }),
  );
  render(<PersonalTokenDialog open onOpenChange={jest.fn()} />);

  expect(await screen.findByText(mockI18n.t("com_ai_access.scope_own_only"))).toBeInTheDocument();
  expect(screen.queryByText(mockI18n.t("com_ai_access.admin_banner", { days: "30" }))).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Generate my key" }));
  await waitFor(() => expect(issuePersonalTokenApi).toHaveBeenCalledTimes(1));
});

it("shows expired status and prevents issuance when disabled", async () => {
  jest.mocked(getPersonalTokenStatusApi).mockResolvedValue(statusOf({ token: { ...token, is_valid: false } }));
  const { rerender } = render(<PersonalTokenDialog open onOpenChange={jest.fn()} />);
  expect(await screen.findByText("Status: Expired")).toBeInTheDocument();
  rerender(<PersonalTokenDialog open={false} onOpenChange={jest.fn()} />);
  jest.mocked(getPersonalTokenStatusApi).mockResolvedValue(statusOf({ enabled: false }));
  rerender(<PersonalTokenDialog open onOpenChange={jest.fn()} />);
  await screen.findByText(en.com_ai_access.disabled_notice);
  expect(screen.getByRole("button", { name: "Generate my key" })).toBeDisabled();
});

it("retries a failed status request before allowing issuance", async () => {
  jest.mocked(getPersonalTokenStatusApi).mockRejectedValueOnce(new Error("unavailable"));
  render(<PersonalTokenDialog open onOpenChange={jest.fn()} />);
  await userEvent.click(await screen.findByRole("button", { name: "Reload" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "Generate my key" })).toBeEnabled());
  expect(issuePersonalTokenApi).not.toHaveBeenCalled();
});

it("reports copy failures without a success message", async () => {
  jest.mocked(copyText).mockRejectedValueOnce(new Error("clipboard unavailable"));
  render(<PersonalTokenDialog open onOpenChange={jest.fn()} />);
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: en.com_ai_access.copy_all })); });
  expect(mockToast).toHaveBeenCalledWith({ message: en.com_ai_access.copy_failed, status: "error" });
  expect(mockToast).not.toHaveBeenCalledWith(expect.objectContaining({ status: "success" }));
});
