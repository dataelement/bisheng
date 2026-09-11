import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createInstance } from "i18next";
import type { ButtonHTMLAttributes, ReactNode } from "react";
import {
  deletePersonalTokenApi, getPersonalTokenStatusApi, issuePersonalTokenApi,
  type PersonalTokenItem,
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
  Button: ({ children, disabled, onClick, loading, "aria-label": label }:
    ButtonHTMLAttributes<HTMLButtonElement> & {
      color?: string; variant?: string; size?: string; iconOnly?: boolean; loading?: boolean;
    }) => <button disabled={disabled || loading} onClick={onClick} aria-label={label}>{children}</button>,
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

beforeAll(async () => {
  await mockI18n.init({
    lng: "en", fallbackLng: "en", interpolation: { escapeValue: false },
    resources: { en: { translation: en }, "zh-Hans": { translation: zh }, ja: { translation: ja } },
  });
});
beforeEach(async () => {
  await mockI18n.changeLanguage("en");
  jest.mocked(getPersonalTokenStatusApi).mockResolvedValue({ enabled: true, token: null, holder_is_admin: false });
  jest.mocked(issuePersonalTokenApi).mockResolvedValue({ ...token, plaintext, holder_is_admin: false });
  jest.mocked(deletePersonalTokenApi).mockResolvedValue({ revoked: 1 });
  jest.mocked(copyText).mockResolvedValue();
  mockConfirm.mockResolvedValue(true);
});

it.each(["en", "zh-Hans", "ja"])("copies the visible prompt in %s with the current instance URLs", async (language) => {
  await mockI18n.changeLanguage(language);
  render(<PersonalTokenDialog open onOpenChange={jest.fn()} />);
  await waitFor(() => expect(screen.getByRole("button", { name: mockI18n.t("com_personal_token.get_key") })).toBeEnabled());
  const prompt = mockI18n.t("com_personal_token.install_prompt", {
    skillPackUrl: "http://localhost:3080/api/v1/open-api/skill-packs/bisheng-knowledge-search",
    tokenPageUrl: "http://localhost:3080/workspace/settings/account?api-token=1",
  });
  expect(screen.getByText(prompt, { normalizer: (value) => value })).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: mockI18n.t("com_personal_token.copy_all") }));
  expect(copyText).toHaveBeenCalledWith(prompt);
});

it("transitions to an issued key, protects it until saved, and only shows the mask after reopening", async () => {
  const onOpenChange = jest.fn();
  const { rerender } = render(<PersonalTokenDialog open onOpenChange={onOpenChange} />);
  await waitFor(() => expect(screen.getByRole("button", { name: "Get API Key" })).toBeEnabled());
  await userEvent.click(screen.getByRole("button", { name: "Get API Key" }));
  expect(await screen.findByText(plaintext)).toBeInTheDocument();
  expect(screen.getByText("Status: Valid")).toBeInTheDocument();
  expect(screen.getByText("Expires on: 2027-09-11")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Close" })).toBeDisabled();
  await userEvent.click(screen.getByRole("button", { name: "Copy API Key" }));
  expect(copyText).toHaveBeenCalledWith(plaintext);
  await userEvent.click(screen.getByRole("checkbox"));
  await userEvent.click(screen.getByRole("button", { name: "Close" }));
  expect(onOpenChange).toHaveBeenCalledWith(false);
  rerender(<PersonalTokenDialog open={false} onOpenChange={onOpenChange} />);
  jest.mocked(getPersonalTokenStatusApi).mockResolvedValue({ enabled: true, token, holder_is_admin: false });
  rerender(<PersonalTokenDialog open onOpenChange={onOpenChange} />);
  expect(await screen.findByText(token.key_mask)).toBeInTheDocument();
  expect(screen.queryByText(plaintext)).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Copy API Key" })).not.toBeInTheDocument();
});

it("can regenerate a key and return to the empty card after deletion", async () => {
  jest.mocked(getPersonalTokenStatusApi).mockResolvedValue({ enabled: true, token, holder_is_admin: false });
  render(<PersonalTokenDialog open onOpenChange={jest.fn()} />);
  await userEvent.click(await screen.findByRole("button", { name: "Get a new key" }));
  expect(await screen.findByText(plaintext)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("checkbox"));
  await userEvent.click(screen.getByRole("button", { name: "Delete API Key" }));
  await waitFor(() => expect(deletePersonalTokenApi).toHaveBeenCalledTimes(1));
  expect(screen.queryByText(plaintext)).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Get API Key" })).toBeEnabled();
});

it("shows expired status and prevents issuance when disabled", async () => {
  jest.mocked(getPersonalTokenStatusApi).mockResolvedValue({ enabled: true, token: { ...token, is_valid: false }, holder_is_admin: false });
  const { rerender } = render(<PersonalTokenDialog open onOpenChange={jest.fn()} />);
  expect(await screen.findByText("Status: Expired")).toBeInTheDocument();
  rerender(<PersonalTokenDialog open={false} onOpenChange={jest.fn()} />);
  jest.mocked(getPersonalTokenStatusApi).mockResolvedValue({ enabled: false, token: null, holder_is_admin: false });
  rerender(<PersonalTokenDialog open onOpenChange={jest.fn()} />);
  await screen.findByText(en.com_personal_token_disabled);
  expect(screen.getByRole("button", { name: "Get API Key" })).toBeDisabled();
});

it("retries a failed status request before allowing issuance", async () => {
  jest.mocked(getPersonalTokenStatusApi).mockRejectedValueOnce(new Error("unavailable"));
  render(<PersonalTokenDialog open onOpenChange={jest.fn()} />);
  await userEvent.click(await screen.findByRole("button", { name: "Reload" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "Get API Key" })).toBeEnabled());
  expect(issuePersonalTokenApi).not.toHaveBeenCalled();
});

it("reports copy failures without a success message", async () => {
  jest.mocked(copyText).mockRejectedValueOnce(new Error("clipboard unavailable"));
  render(<PersonalTokenDialog open onOpenChange={jest.fn()} />);
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Copy prompt" })); });
  expect(mockToast).toHaveBeenCalledWith({ message: en.com_personal_token.copy_failed, status: "error" });
  expect(mockToast).not.toHaveBeenCalledWith(expect.objectContaining({ status: "success" }));
});
