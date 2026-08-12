import { SubjectSearchUser } from "@/components/bs-comp/permission/SubjectSearchUser";
import { userContext } from "@/contexts/userContext";
import { getGrantSubjectUsersApi } from "@/controllers/API/permission";
import { render, screen, waitFor } from "@/test/test-utils";
import { act, fireEvent } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}));

vi.mock("@/controllers/API/permission", () => ({
  getGrantSubjectUsersApi: vi.fn(),
}));

vi.mock("@/components/bs-ui/input", () => ({
  SearchInput: ({ value, onChange, placeholder }: any) => (
    <input value={value} onChange={onChange} placeholder={placeholder} />
  ),
}));

vi.mock("@/components/bs-ui/checkBox", () => ({
  Checkbox: ({ checked }: any) => <input type="checkbox" readOnly checked={checked} />,
}));

const mockedGrantSubjectUsers = vi.mocked(getGrantSubjectUsersApi);

describe("SubjectSearchUser", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedGrantSubjectUsers.mockResolvedValue({ data: [], total: 0 } as any);
  });

  it("asks who may be granted this resource, not who the caller administers", async () => {
    mockedGrantSubjectUsers.mockResolvedValue({
      data: [{ user_id: 11, user_name: "Carol", primary_department_path: "总部/产品部" }],
      total: 1,
    } as any);

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

    expect(mockedGrantSubjectUsers).toHaveBeenCalledWith(
      "knowledge_space",
      "88",
      { keyword: "", page: 1, pageSize: 50 },
      { signal: expect.any(AbortSignal) },
    );
  });

  it("asks for nobody until it knows which resource is being granted", async () => {
    render(
      <userContext.Provider value={{ user: { user_id: 7 } } as any}>
        <SubjectSearchUser value={[]} onChange={vi.fn()} />
      </userContext.Provider>,
    );

    await waitFor(() => {
      expect(screen.getByPlaceholderText("search.user")).toBeInTheDocument();
    });
    // No resource means no scope to authorize against — asking anyway would be a
    // guaranteed permission error.
    expect(mockedGrantSubjectUsers).not.toHaveBeenCalled();
  });

  it("sends the keyword to the server rather than filtering a loaded page", async () => {
    mockedGrantSubjectUsers.mockResolvedValue({
      data: [{ user_id: 8, user_name: "Alice", external_id: "alice-001" }],
      total: 1,
    } as any);

    vi.useFakeTimers();
    try {
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

      fireEvent.change(screen.getByPlaceholderText("search.user"), {
        target: { value: "ali" },
      });
      await act(async () => {
        vi.advanceTimersByTime(300);
        await Promise.resolve();
        await Promise.resolve();
      });

      expect(screen.getByText("Alice")).toBeInTheDocument();
      expect(mockedGrantSubjectUsers).toHaveBeenLastCalledWith(
        "knowledge_space",
        "88",
        { keyword: "ali", page: 1, pageSize: 50 },
        { signal: expect.any(AbortSignal) },
      );
    } finally {
      vi.useRealTimers();
    }
  });
});
