import {
  deleteEPlusBotConfigApi,
  getEPlusBotConfigApi,
  listEPlusBindableSpacesApi,
  saveEPlusBotConfigApi,
} from "@/controllers/API/eplus";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { EPlusRobotSettings } from "@/pages/BuildPage/assistant/editAssistant/EPlusRobotSettings";
import { getRobotDebugStatus } from "@/controllers/API/eplusDebug";
import { fireEvent, render, screen, waitFor } from "@/test/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock("@/controllers/API/eplusDebug", () => ({ getRobotDebugStatus: vi.fn().mockResolvedValue(false) }));

vi.mock("@/controllers/API/eplus", () => ({
  deleteEPlusBotConfigApi: vi.fn(),
  getEPlusBotConfigApi: vi.fn(),
  listEPlusBindableSpacesApi: vi.fn(),
  saveEPlusBotConfigApi: vi.fn(),
}));

vi.mock("@/controllers/request", () => ({
  captureAndAlertRequestErrorHoc: vi.fn((promise: Promise<unknown>) => promise),
}));

vi.mock("@/components/bs-ui/toast/use-toast", () => ({
  toast: vi.fn(),
}));

vi.mock("@/components/bs-ui/alertDialog/useConfirm", () => ({
  bsConfirm: vi.fn(({ onOk }) => onOk?.(() => undefined)),
}));

vi.mock("@/components/bs-ui/select/multi", () => ({
  __esModule: true,
  default: ({ options, value, onChange, placeholder }) => (
    <div>
      <span>{placeholder}</span>
      <span data-testid="selected-spaces">{value.join(",")}</span>
      <button type="button" onClick={() => onChange(options.map((item) => item.value))}>
        select-spaces
      </button>
    </div>
  ),
}));

const existingConfig = {
  id: 1,
  assistant_id: "assistant-1",
  bot_id: "bot-1",
  connection_url: "ws://eplus.example.test/im_openws?bizid=1",
  credential_version: 1,
  scope_version: 2,
  enabled: true,
  is_deleted: false,
  connection_status: "ERROR" as const,
  secret_configured: true,
  ca_configured: false,
  ca_sha256: null,
  media_hosts: ["media.example.test"],
  space_ids: [10],
  insecure_transport: true,
};

describe("EPlusRobotSettings", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(captureAndAlertRequestErrorHoc).mockImplementation(
      (promise: Promise<unknown>) => promise as never,
    );
    vi.mocked(getEPlusBotConfigApi).mockResolvedValue(existingConfig);
    vi.mocked(listEPlusBindableSpacesApi).mockResolvedValue([
      { id: 10, name: "Space A" },
      { id: 20, name: "Space B" },
    ]);
    vi.mocked(saveEPlusBotConfigApi).mockResolvedValue({
      ...existingConfig,
      connection_status: "CONNECTING",
      space_ids: [10, 20],
    });
    vi.mocked(deleteEPlusBotConfigApi).mockResolvedValue(true);
    vi.mocked(getRobotDebugStatus).mockResolvedValue(false);
  });

  it("hides the debug entry when authorization or deployment is unavailable", async () => {
    render(<EPlusRobotSettings assistantId="assistant-1" />);
    await screen.findByDisplayValue("bot-1");
    expect(screen.queryByRole("button", { name: "build.robotDebug.open" })).not.toBeInTheDocument();
  });

  it("opens the same-origin debug page with this assistant and no credentials", async () => {
    vi.mocked(getRobotDebugStatus).mockResolvedValue(true);
    const open = vi.spyOn(window, "open").mockImplementation(() => null);
    render(<EPlusRobotSettings assistantId="assistant-1" />);
    fireEvent.click(await screen.findByRole("button", { name: "build.robotDebug.open" }));
    expect(open).toHaveBeenCalledWith(expect.stringContaining("/robot-debug?assistantId=assistant-1"), "_blank", "noopener,noreferrer");
    open.mockRestore();
  });

  it("hides CA controls and preserves an existing certificate when saving spaces", async () => {
    vi.mocked(getEPlusBotConfigApi).mockResolvedValue({
      ...existingConfig,
      ca_configured: true,
      ca_sha256: "existing-certificate-hash",
    });
    render(<EPlusRobotSettings assistantId="assistant-1" />);

    expect(await screen.findByDisplayValue("bot-1")).toBeInTheDocument();
    expect(screen.getByLabelText("build.eplusSecret")).toHaveValue("");
    expect(screen.getByText("build.eplusWsWarning")).toBeInTheDocument();
    expect(screen.getByText("build.eplusStatusError")).toBeInTheDocument();
    expect(screen.getByText("build.eplusScopeNotice")).toBeInTheDocument();
    expect(screen.queryByLabelText("build.eplusMediaHosts")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("build.eplusCaCertificate")).not.toBeInTheDocument();
    expect(screen.queryByText("build.eplusCaConfigured")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "build.eplusRemoveCa" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "select-spaces" }));
    fireEvent.click(screen.getByRole("button", { name: "build.eplusSave" }));

    await waitFor(() => expect(saveEPlusBotConfigApi).toHaveBeenCalledTimes(1));
    expect(saveEPlusBotConfigApi).toHaveBeenCalledWith(
      "assistant-1",
      expect.objectContaining({
        bot_id: "bot-1",
        secret: undefined,
        remove_ca: false,
        media_hosts: [],
        space_ids: [10, 20],
        enabled: true,
      }),
    );
    expect(vi.mocked(saveEPlusBotConfigApi).mock.calls[0][1].ca_pem).toBeUndefined();
  });

  it("keeps the connected status badge on one line without shrinking", async () => {
    vi.mocked(getEPlusBotConfigApi).mockResolvedValue({
      ...existingConfig,
      connection_status: "AUTHENTICATED",
    });
    render(<EPlusRobotSettings assistantId="assistant-1" />);

    expect(await screen.findByText("build.eplusStatusAuthenticated")).toHaveClass(
      "whitespace-nowrap",
      "shrink-0",
    );
  });

  it("blocks saving an incomplete new configuration", async () => {
    vi.mocked(getEPlusBotConfigApi).mockResolvedValue(null);
    render(<EPlusRobotSettings assistantId="assistant-1" />);

    await screen.findByText("build.eplusNotConfigured");
    expect(screen.queryByRole("switch", { name: "build.eplusEnabled" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "build.eplusSave" }));

    expect(await screen.findByText("build.eplusRequiredWhenEnabled")).toBeInTheDocument();
    expect(saveEPlusBotConfigApi).not.toHaveBeenCalled();
  });

  it("enables robot access when saving a complete new configuration", async () => {
    vi.mocked(getEPlusBotConfigApi).mockResolvedValue(null);
    render(<EPlusRobotSettings assistantId="assistant-1" />);

    await screen.findByText("build.eplusNotConfigured");
    fireEvent.change(screen.getByLabelText("build.eplusBotId"), {
      target: { value: "bot-1" },
    });
    fireEvent.change(screen.getByLabelText("build.eplusConnectionUrl"), {
      target: { value: "wss://eplus.example.test/im_openws?bizid=1" },
    });
    fireEvent.change(screen.getByLabelText("build.eplusSecret"), {
      target: { value: "test-secret" },
    });
    fireEvent.click(screen.getByRole("button", { name: "build.eplusSave" }));

    await waitFor(() => expect(saveEPlusBotConfigApi).toHaveBeenCalledWith(
      "assistant-1",
      expect.objectContaining({ enabled: true }),
    ));
  });

  it("re-enables a previously disabled robot binding when saving", async () => {
    vi.mocked(getEPlusBotConfigApi).mockResolvedValue({
      ...existingConfig,
      enabled: false,
      connection_status: "DISABLED",
    });
    render(<EPlusRobotSettings assistantId="assistant-1" />);

    await screen.findByDisplayValue("bot-1");
    expect(screen.queryByRole("switch", { name: "build.eplusEnabled" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "build.eplusSave" }));

    await waitFor(() => expect(saveEPlusBotConfigApi).toHaveBeenCalledWith(
      "assistant-1",
      expect.objectContaining({ enabled: true }),
    ));
  });

  it("disconnects and removes an existing robot binding after confirmation", async () => {
    render(<EPlusRobotSettings assistantId="assistant-1" />);

    await screen.findByDisplayValue("bot-1");
    fireEvent.click(screen.getByRole("button", { name: "build.eplusDisconnect" }));

    await waitFor(() => expect(deleteEPlusBotConfigApi).toHaveBeenCalledWith("assistant-1"));
    expect(await screen.findByText("build.eplusNotConfigured")).toBeInTheDocument();
  });
});
