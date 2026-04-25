import { SubjectSearchUser } from "@/components/bs-comp/permission/SubjectSearchUser";
import { getKnowledgeSpaceGrantUsersApi } from "@/controllers/API/permission";
import { userContext } from "@/contexts/userContext";
import {
  getGroupUsersApi,
  getUserMembershipGroupsApi,
  getUsersApi,
} from "@/controllers/API/user";
import { render, screen, waitFor } from "@/test/test-utils";
import { act, fireEvent } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}));

vi.mock("@/controllers/API/user", () => ({
  getUsersApi: vi.fn(),
  getGroupUsersApi: vi.fn(),
  getUserMembershipGroupsApi: vi.fn(),
}));

vi.mock("@/controllers/API/permission", () => ({
  getKnowledgeSpaceGrantUsersApi: vi.fn(),
}));

vi.mock("@/components/bs-ui/input", () => ({
  SearchInput: ({ value, onChange, placeholder }: any) => (
    <input value={value} onChange={onChange} placeholder={placeholder} />
  ),
}));

vi.mock("@/components/bs-ui/checkBox", () => ({
  Checkbox: ({ checked }: any) => <input type="checkbox" readOnly checked={checked} />,
}));

const mockedGetUsersApi = vi.mocked(getUsersApi);
const mockedGetGroupUsersApi = vi.mocked(getGroupUsersApi);
const mockedGetUserMembershipGroupsApi = vi.mocked(getUserMembershipGroupsApi);
const mockedGetKnowledgeSpaceGrantUsersApi = vi.mocked(getKnowledgeSpaceGrantUsersApi);

describe("SubjectSearchUser", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("falls back to current user's group peers when managed user search returns empty", async () => {
    mockedGetUsersApi.mockResolvedValue({ data: [], total: 0 } as any);
    mockedGetUserMembershipGroupsApi.mockResolvedValue([
      { id: 101, group_name: "研发组" },
    ] as any);
    mockedGetGroupUsersApi.mockResolvedValue([
      { user_id: 8, user_name: "Alice", external_id: "alice-001" },
      { user_id: 9, user_name: "Bob", external_id: "bob-001" },
    ] as any);

    render(
      <userContext.Provider value={{ user: { user_id: 7 } } as any}>
        <SubjectSearchUser value={[]} onChange={vi.fn()} />
      </userContext.Provider>,
    );

    await waitFor(() => {
      expect(screen.getByText("Alice")).toBeInTheDocument();
    });

    expect(mockedGetUserMembershipGroupsApi).toHaveBeenCalledWith(7, {
      signal: expect.any(AbortSignal),
    });
    expect(mockedGetGroupUsersApi).toHaveBeenCalledWith(101);
  });

  it("uses full-scope grant candidates for knowledge-space permission grants", async () => {
    mockedGetKnowledgeSpaceGrantUsersApi.mockResolvedValue([
      { user_id: 11, user_name: "Carol", primary_department_path: "总部/产品部" },
    ] as any);

    render(
      <userContext.Provider value={{ user: { user_id: 7 } } as any}>
        <SubjectSearchUser
          value={[]}
          onChange={vi.fn()}
          resourceType="knowledge_space"
          resourceId="88"
        />
      </userContext.Provider>,
    );

    await waitFor(() => {
      expect(screen.getByText("Carol")).toBeInTheDocument();
    });

    expect(mockedGetKnowledgeSpaceGrantUsersApi).toHaveBeenCalledWith("88", {
      keyword: "",
      page: 1,
      page_size: 1000,
    });
    expect(mockedGetUsersApi).not.toHaveBeenCalled();
    expect(mockedGetUserMembershipGroupsApi).not.toHaveBeenCalled();
  });

  it("filters same-group peers by keyword on subsequent search", async () => {
    mockedGetUsersApi.mockResolvedValue({ data: [], total: 0 } as any);
    mockedGetUserMembershipGroupsApi.mockResolvedValue([
      { id: 101, group_name: "研发组" },
    ] as any);
    mockedGetGroupUsersApi.mockResolvedValue([
      { user_id: 8, user_name: "Alice", external_id: "alice-001" },
      { user_id: 9, user_name: "Bob", external_id: "bob-001" },
    ] as any);

    vi.useFakeTimers();
    try {
      render(
        <userContext.Provider value={{ user: { user_id: 7 } } as any}>
          <SubjectSearchUser value={[]} onChange={vi.fn()} />
        </userContext.Provider>,
      );

      const input = screen.getByPlaceholderText("search.user");
      fireEvent.change(input, { target: { value: "ali" } });
      await act(async () => {
        vi.advanceTimersByTime(300);
        await Promise.resolve();
        await Promise.resolve();
      });

      expect(screen.getByText("Alice")).toBeInTheDocument();
      expect(screen.queryByText("Bob")).not.toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });
});
