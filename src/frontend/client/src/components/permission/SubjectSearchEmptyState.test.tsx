import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { SubjectSearchDepartment } from "./SubjectSearchDepartment";
import { SubjectSearchUserGroup } from "./SubjectSearchUserGroup";

type Locale = "zh-Hans" | "en" | "ja";
let mockLocale: Locale = "zh-Hans";

jest.mock("~/api/permission", () => ({
  getDepartmentChildren: jest.fn(),
  searchDepartments: jest.fn(),
  getUserGroups: jest.fn(),
}));

jest.mock("~/hooks", () => ({
  useLocalize: () => (key: string) => {
    const labels: Record<string, string> = jest.requireActual(
      `~/locales/${mockLocale}/translation.json`,
    ).com_permission;
    return key.startsWith("com_permission.")
      ? labels[key.slice("com_permission.".length)]
      : key;
  },
}));

const locales: Locale[] = ["zh-Hans", "en", "ja"];

describe.each(locales)("permission search empty states in %s", (locale) => {
  const labels = jest.requireActual(`~/locales/${locale}/translation.json`).com_permission;
  const departmentMessage = labels.empty_search_departments;
  const groupMessage = labels.empty_search_user_groups;
  beforeEach(() => { mockLocale = locale; });

  it("identifies an empty department search and restores the browse state after clearing", async () => {
    const childrenApi = jest.fn().mockResolvedValue([]);
    const searchApi = jest.fn().mockResolvedValue({ roots: [], truncated: false });
    render(
      <SubjectSearchDepartment
        value={[]}
        onChange={jest.fn()}
        resourceType="knowledge_space"
        resourceId="space-1"
        includeChildren={false}
        departmentChildrenApi={childrenApi}
        departmentSearchApi={searchApi}
      />,
    );
    expect(await screen.findByText(labels.empty_departments)).toBeInTheDocument();
    const input = screen.getByRole("textbox");
    fireEvent.change(input, { target: { value: "missing" } });

    expect(await screen.findByText(departmentMessage)).toBeInTheDocument();
    await waitFor(() => expect(searchApi).toHaveBeenCalledWith(
      "knowledge_space", "space-1", "missing", 50, { signal: expect.any(AbortSignal) },
    ));
    expect(screen.queryByText(labels.empty_search)).toBeNull();

    fireEvent.change(input, { target: { value: "" } });
    expect(await screen.findByText(labels.empty_departments)).toBeInTheDocument();
    expect(screen.queryByText(departmentMessage)).toBeNull();
  });

  it("identifies an empty user-group search and keeps existing groups available after clearing", async () => {
    const userGroupsApi = jest.fn().mockResolvedValue([{ id: 7, group_name: "Engineering" }]);
    render(
      <SubjectSearchUserGroup
        value={[]}
        onChange={jest.fn()}
        resourceType="knowledge_space"
        resourceId="space-1"
        userGroupsApi={userGroupsApi}
      />,
    );
    expect(await screen.findByText("Engineering")).toBeInTheDocument();
    const input = screen.getByRole("textbox");
    fireEvent.change(input, { target: { value: "missing" } });
    expect(await screen.findByText(groupMessage)).toBeInTheDocument();
    expect(screen.queryByText(labels.empty_search)).toBeNull();

    fireEvent.change(input, { target: { value: "" } });
    expect(await screen.findByText("Engineering")).toBeInTheDocument();
    expect(screen.queryByText(groupMessage)).toBeNull();
  });
});
