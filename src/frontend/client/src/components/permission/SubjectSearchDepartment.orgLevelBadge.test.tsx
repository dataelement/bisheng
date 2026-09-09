import { fireEvent, render, screen, within } from "@testing-library/react";

import { SubjectSearchDepartment } from "./SubjectSearchDepartment";

jest.mock("~/hooks", () => ({
  useLocalize: () => (key: string) => key,
}));

jest.mock("~/api/permission", () => ({
  getResourceGrantDepartments: jest.fn(),
}));

describe("SubjectSearchDepartment org_level badge", () => {
  it("shows first-level squad badge and hides descendant squad badge", async () => {
    const loadDepartments = jest.fn().mockResolvedValue([
      {
        id: 1,
        dept_id: "dept-1",
        name: "公司",
        org_level: "company",
        parent_id: null,
        children: [
          {
            id: 2,
            dept_id: "dept-2",
            name: "第一层班组",
            org_level: "squad",
            parent_id: 1,
            children: [
              {
                id: 3,
                dept_id: "dept-3",
                name: "班组下层",
                org_level: "squad",
                parent_id: 2,
                children: [],
              },
            ],
          },
        ],
      },
    ]);

    render(
      <SubjectSearchDepartment
        value={[]}
        onChange={jest.fn()}
        includeChildren
        onIncludeChildrenChange={jest.fn()}
        selectionMode="multiple"
        loadDepartments={loadDepartments}
      />,
    );

    const companyLabel = await screen.findByText("公司");
    fireEvent.click(within(companyLabel.parentElement as HTMLElement).getByRole("button"));

    const firstSquadLabel = await screen.findByText("第一层班组");
    expect(
      within(firstSquadLabel.parentElement as HTMLElement).getByText(
        "com_permission.org_level_squad",
      ),
    ).toBeInTheDocument();

    fireEvent.click(within(firstSquadLabel.parentElement as HTMLElement).getByRole("button"));
    const nestedLabel = await screen.findByText("班组下层");
    expect(
      within(nestedLabel.parentElement as HTMLElement).queryByText(
        "com_permission.org_level_squad",
      ),
    ).not.toBeInTheDocument();
  });
});
