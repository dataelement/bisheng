import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { useContext } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { LocationProvider, locationContext } from "@/contexts/locationContext";
import type { AppConfig } from "@/types/api/app";

const mocks = vi.hoisted(() => ({ env: vi.fn(), bench: vi.fn() }));
vi.mock("@/controllers/API", () => ({
  getAppConfig: mocks.env,
  getWorkstationConfigApi: mocks.bench,
}));
const environment: AppConfig = {
  env: "test",
  uns_support: [],
  office_url: "",
  dialog_tips: "",
  dialog_quick_search: "",
  websocket_url: "",
  pro: false,
  dashboard_pro: false,
  sso: false,
  application_usage_tips: false,
  show_github_and_help: false,
  version: "",
  enable_registration: false,
  uploaded_files_maximum_size: 50,
  enable_etl4lm: false,
  knowledges: {
    version_management: { enabled: true, simhash_similarity_threshold: 0.85 },
  },
};
function Consumer() {
  const { appConfig, reloadConfig } = useContext(locationContext);
  return (
    <>
      <output data-testid="flag">
        {String(appConfig.versionManagementEnabled)}
      </output>
      <button onClick={reloadConfig}>reload</button>
    </>
  );
}
beforeEach(() => {
  vi.clearAllMocks();
  mocks.bench.mockResolvedValue({ menuShow: true });
});
afterEach(cleanup);

it("keeps the unprovided Context default off", () => {
  render(<Consumer />);
  expect(screen.getByTestId("flag")).toHaveTextContent("false");
  expect(mocks.env).not.toHaveBeenCalled();
});
it.each([undefined, false, true, "true", "false", 1, {}])(
  "maps only actual env enabled===true: %j",
  async (enabled) => {
    mocks.env.mockResolvedValue({
      ...environment,
      knowledges:
        enabled === undefined ? undefined : { version_management: { enabled } },
    });
    render(
      <LocationProvider>
        <Consumer />
      </LocationProvider>,
    );
    await waitFor(() => expect(mocks.bench).toHaveBeenCalledOnce());
    expect(screen.getByTestId("flag")).toHaveTextContent(
      String(enabled === true),
    );
  },
);
it("does not enable history while the real environment request is still pending", async () => {
  let resolve!: (value: AppConfig) => void;
  mocks.env.mockReturnValue(
    new Promise<AppConfig>((yes) => {
      resolve = yes;
    }),
  );
  render(
    <LocationProvider>
      <Consumer />
    </LocationProvider>,
  );
  expect(screen.getByTestId("flag")).toHaveTextContent("false");
  await act(async () => resolve(environment));
  await waitFor(() =>
    expect(screen.getByTestId("flag")).toHaveTextContent("true"),
  );
});
it("clears an earlier true flag when reloaded env no longer contains the capability", async () => {
  mocks.env
    .mockResolvedValueOnce(environment)
    .mockResolvedValueOnce({ ...environment, knowledges: {} });
  render(
    <LocationProvider>
      <Consumer />
    </LocationProvider>,
  );
  await waitFor(() =>
    expect(screen.getByTestId("flag")).toHaveTextContent("true"),
  );
  fireEvent.click(screen.getByRole("button", { name: "reload" }));
  await waitFor(() =>
    expect(screen.getByTestId("flag")).toHaveTextContent("false"),
  );
});
