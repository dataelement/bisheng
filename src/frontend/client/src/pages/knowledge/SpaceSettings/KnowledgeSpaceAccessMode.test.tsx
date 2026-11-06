import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { VisibilityType } from "~/api/knowledge";
import { KnowledgeSpaceAccessMode } from "./KnowledgeSpaceAccessMode";

const mockConfirm = jest.fn();

jest.mock("~/hooks", () => ({ useLocalize: () => (key: string) => key }));
jest.mock("~/Providers", () => ({ useConfirm: () => mockConfirm }));

function renderMode(isDepartmentSpace: boolean, disabled = false) {
  const onVisibilityChange = jest.fn();
  render(
    <KnowledgeSpaceAccessMode
      visibility={VisibilityType.APPROVAL}
      mode="edit"
      isDepartmentSpace={isDepartmentSpace}
      disabled={disabled}
      isReleased={true}
      onVisibilityChange={onVisibilityChange}
      onReleasedChange={jest.fn()}
    />,
  );
  return onVisibilityChange;
}

describe("department knowledge space access mode", () => {
  beforeEach(() => mockConfirm.mockResolvedValue(true));

  it("disables private for department spaces without disabling shared", async () => {
    const change = renderMode(true);
    const privateOption = screen.getByRole("radio", {
      name: /com_unified_permission.private/,
    });
    const sharedOption = screen.getByRole("radio", {
      name: /com_unified_permission.shared/,
    });
    expect(privateOption).toBeDisabled();
    expect(sharedOption).not.toBeDisabled();
    expect(sharedOption).toHaveAttribute("aria-checked", "true");
    expect(
      screen.getByText("com_knowledge.department_private_disabled"),
    ).toBeInTheDocument();
    const user = userEvent.setup();
    await user.click(privateOption);
    sharedOption.focus();
    await user.keyboard("{ArrowLeft} ");
    expect(change).not.toHaveBeenCalled();
    expect(mockConfirm).not.toHaveBeenCalled();
    expect(sharedOption).toHaveAttribute("aria-checked", "true");
  });

  it("retains the private confirmation and change for normal spaces", async () => {
    const change = renderMode(false);
    await userEvent
      .setup()
      .click(
        screen.getByRole("radio", { name: /com_unified_permission.private/ }),
      );
    await waitFor(() =>
      expect(change).toHaveBeenCalledWith(VisibilityType.PRIVATE),
    );
    expect(mockConfirm).toHaveBeenCalledTimes(1);
    expect(
      screen.queryByText("com_knowledge.department_private_disabled"),
    ).not.toBeInTheDocument();
  });

  it("does not change a normal space when private confirmation is cancelled", async () => {
    mockConfirm.mockResolvedValue(false);
    const change = renderMode(false);
    await userEvent
      .setup()
      .click(
        screen.getByRole("radio", { name: /com_unified_permission.private/ }),
      );
    expect(mockConfirm).toHaveBeenCalledTimes(1);
    expect(change).not.toHaveBeenCalled();
  });

  it("keeps both options disabled when the caller cannot edit", () => {
    renderMode(true, true);
    for (const option of screen.getAllByRole("radio"))
      expect(option).toBeDisabled();
  });

  it("keeps department shared options editable", async () => {
    const change = renderMode(true);
    await userEvent
      .setup()
      .click(screen.getByRole("switch", { name: /review_join/ }));
    expect(change).toHaveBeenCalledWith(VisibilityType.PUBLIC);
    expect(
      screen.getByRole("switch", { name: /publish_to_square/ }),
    ).not.toBeDisabled();
  });
});
