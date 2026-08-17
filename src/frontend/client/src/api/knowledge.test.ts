import request from "~/api/request";
import {
    getDepartmentSpacesApi,
    getJoinedSpacesApi,
    getMineSpacesApi,
} from "~/api/knowledge";

jest.mock("~/api/request", () => ({
    __esModule: true,
    default: {
        get: jest.fn(),
    },
}));

const mockedRequest = request as jest.Mocked<typeof request>;

function spacePayload(spaceKind?: string) {
    return {
        status_code: 200,
        status_message: "success",
        data: [
            {
                id: 7,
                name: "space-7",
                auth_type: "private",
                space_kind: spaceKind,
            },
        ],
    };
}

describe("knowledge space list entry mapping", () => {
    it("marks department entries without backend department metadata", async () => {
        mockedRequest.get.mockResolvedValueOnce(spacePayload());

        const spaces = await getDepartmentSpacesApi({ order_by: "update_time" });

        expect(spaces).toHaveLength(1);
        expect(spaces[0].spaceKind).toBe("department");
        expect(spaces[0].departmentId).toBeUndefined();
        expect(spaces[0].departmentName).toBeUndefined();
        expect(mockedRequest.get).toHaveBeenCalledWith(
            "/api/v1/knowledge/space/department",
            { params: { order_by: "update_time" } },
        );
    });

    it("keeps mine and joined entries normal regardless of raw defaults", async () => {
        mockedRequest.get
            .mockResolvedValueOnce(spacePayload("department"))
            .mockResolvedValueOnce(spacePayload());

        const mine = await getMineSpacesApi();
        const joined = await getJoinedSpacesApi();

        expect(mine[0].spaceKind).toBe("normal");
        expect(joined[0].spaceKind).toBe("normal");
    });
});
