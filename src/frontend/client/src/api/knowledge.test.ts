import request from "~/api/request";
import { getSquareSpacesApi, VisibilityType } from "./knowledge";

jest.mock("~/api/request", () => ({
  __esModule: true,
  default: {
    get: jest.fn(),
  },
}));

const mockGet = request.get as jest.Mock;

describe("getSquareSpacesApi", () => {
  it("maps pending square items from is_pending when subscription_status is absent", async () => {
    mockGet.mockResolvedValue({
      data: {
        total: 1,
        data: [
          {
            space: {
              id: 101,
              name: "Pending space",
              auth_type: VisibilityType.APPROVAL,
              user_id: 7,
              user_name: "owner",
              is_released: true,
            },
            is_pending: true,
            file_num: 3,
            follower_num: 2,
          },
        ],
      },
    });

    const result = await getSquareSpacesApi();

    expect(result.data[0]).toMatchObject({
      id: "101",
      isPending: true,
      isFollowed: false,
      squareStatus: "pending",
    });
  });
});
