import { fireEvent, render, screen, within } from "@testing-library/react";
import type { TAuthContext } from "~/common";
import { AuthContext } from "~/hooks/AuthContext";
import { PermissionDraftEditor } from "./PermissionDraftEditor";
import { SubjectSearchUser } from "./SubjectSearchUser";

jest.mock("~/api/permission", () => ({ searchUsers: jest.fn() }));
jest.mock("~/hooks", () => ({ useLocalize: () => (key: string) => key }));
jest.mock("~/hooks/AuthContext", () => ({
  AuthContext: jest.requireActual("react").createContext(undefined),
}));

const loginContext: TAuthContext = {
  user: {
    id: "1",
    username: "admin",
    name: "admin",
    avatar: "/object/bucket/avatar/1/current.png?signature=fresh",
    email: "",
    role: "admin",
    provider: "local",
    createdAt: "",
    updatedAt: "",
  },
  token: undefined,
  isAuthenticated: true,
  isUserLoading: false,
  error: undefined,
  login: jest.fn(),
  logout: jest.fn(),
  setError: jest.fn(),
};

const roster = (
  <PermissionDraftEditor
    value={[{
      subjectType: "user",
      subjectId: 1,
      subjectName: "admin",
      modelKey: "owner",
      modelName: "Owner",
      modelLevel: 4,
      sourceType: "creator",
      protected: true,
      editable: false,
    }]}
    onChange={jest.fn()}
    capabilities={{ canChangeRelation: false, canRemove: false, relationModels: [] }}
  />
);

it("uses the current profile for the creator and disabled picker row by user ID", async () => {
  const peerAvatar = "/object/bucket/avatar/2/current.png";
  const usersApi = jest.fn().mockResolvedValue({
    data: [
      { user_id: 1, user_name: "admin", external_id: "admin", avatar: "/expired.png" },
      { user_id: 2, user_name: "admin", external_id: "another-user", avatar: peerAvatar },
    ],
    total: 2,
  });
  render(
    <AuthContext.Provider value={loginContext}>
      <div data-testid="roster">{roster}</div>
      <div data-testid="picker">
        <SubjectSearchUser
          value={[]}
          onChange={jest.fn()}
          resourceType="knowledge_space"
          resourceId="2"
          disabledIds={[1]}
          usersApi={usersApi}
        />
      </div>
    </AuthContext.Provider>,
  );

  expect(within(screen.getByTestId("roster")).getByRole("img")).toHaveAttribute("src", loginContext.user?.avatar);
  const picker = within(screen.getByTestId("picker"));
  const [creator, peer] = await picker.findAllByRole("img");
  expect(creator).toHaveAttribute("src", loginContext.user?.avatar);
  expect(peer).toHaveAttribute("src", peerAvatar);
  expect(picker.getByRole("checkbox", { checked: true })).toBeDisabled();

  fireEvent.error(creator);
  expect(picker.getByText("A")).toHaveClass("bg-fill-4", "text-white");
});
