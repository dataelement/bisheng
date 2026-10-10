/** @jest-environment node */

import request from "~/api/request";
import {
  deletePersonalTokenApi,
  getPersonalTokenInstallPromptApi,
  getPersonalTokenStatusApi,
  issuePersonalTokenApi,
} from "~/api/personalToken";

jest.mock("~/api/request", () => ({
  __esModule: true,
  default: {
    get: jest.fn(),
    post: jest.fn(),
    delete: jest.fn(),
  },
}));

const mockedRequest = request as jest.Mocked<typeof request>;

describe("personal-token API", () => {
  beforeEach(() => {
    const response = { status_code: 200, data: { enabled: true } };
    mockedRequest.get.mockResolvedValue(response);
    mockedRequest.post.mockResolvedValue(response);
    mockedRequest.delete.mockResolvedValue(response);
  });

  it("uses only JWT-authenticated self-service endpoints", async () => {
    await getPersonalTokenStatusApi();
    await issuePersonalTokenApi();
    await deletePersonalTokenApi();
    await getPersonalTokenInstallPromptApi();

    const errorOptions = { skip403Redirect: true };
    expect(mockedRequest.get).toHaveBeenNthCalledWith(1, "/api/v1/me/api-token", errorOptions);
    expect(mockedRequest.post).toHaveBeenCalledWith(
      "/api/v1/me/api-token",
      undefined,
      errorOptions,
    );
    expect(mockedRequest.delete).toHaveBeenCalledWith(
      "/api/v1/me/api-token",
      errorOptions,
    );
    expect(mockedRequest.get).toHaveBeenNthCalledWith(
      2,
      "/api/v1/me/api-token/install-prompt",
      errorOptions,
    );
  });
});
