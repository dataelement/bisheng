/** @jest-environment node */

import request from "~/api/request";
import { getKnowledgeInfo } from "~/api/linsight";

jest.mock("~/api/request", () => ({
  __esModule: true,
  default: {
    get: jest.fn(),
  },
}));

const mockedRequest = request as jest.Mocked<typeof request>;

describe("organization knowledge list", () => {
  it("requests the visible action for a presentation-boundary check", async () => {
    mockedRequest.get.mockResolvedValue({ data: { data: [] } });

    await getKnowledgeInfo({
      page: 1,
      page_size: 20,
      name: "",
      sort_by: "name",
      preferred_ids: "12,13",
      action: "visible",
    });

    expect(mockedRequest.get).toHaveBeenCalledWith(
      "/api/v1/knowledge?page_num=1&page_size=20&type=0&name=&sort_by=name&preferred_ids=12%2C13&action=visible",
    );
  });
});
