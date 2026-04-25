import { render, screen, waitFor } from "@testing-library/react";

import { getGrantableRelationModels } from "~/api/permission";
import { PermissionDialog } from "./PermissionDialog";

jest.mock("~/hooks", () => ({
  useLocalize: () => (key: string) => key,
}));

jest.mock("~/api/permission", () => ({
  getGrantableRelationModels: jest.fn(),
}));

jest.mock("./PermissionListTab", () => ({
  PermissionListTab: ({ resourceType, resourceId, refreshKey }: any) => (
    <div>{`list:${resourceType}:${resourceId}:${refreshKey}`}</div>
  ),
}));

jest.mock("./PermissionGrantTab", () => ({
  PermissionGrantTab: ({ resourceType, resourceId }: any) => (
    <div>{`grant:${resourceType}:${resourceId}`}</div>
  ),
}));

jest.mock("~/components/ui/Dialog", () => ({
  Dialog: ({ children }: any) => <div>{children}</div>,
  DialogContent: ({ children }: any) => <div>{children}</div>,
  DialogHeader: ({ children }: any) => <div>{children}</div>,
  DialogTitle: ({ children }: any) => <div>{children}</div>,
}));

jest.mock("~/components/ui/Tabs", () => ({
  Tabs: ({ children }: any) => <div>{children}</div>,
  TabsList: ({ children }: any) => <div>{children}</div>,
  TabsTrigger: ({ children }: any) => <button type="button">{children}</button>,
  TabsContent: ({ children }: any) => <div>{children}</div>,
}));

const mockedGetGrantableRelationModels = jest.mocked(getGrantableRelationModels);

describe("PermissionDialog", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockedGetGrantableRelationModels.mockResolvedValue([
      {
        id: "viewer",
        name: "Viewer",
        relation: "viewer",
        permissions: [],
        is_system: true,
      },
    ]);
  });

  it("loads grantable relation models once when opened", async () => {
    render(
      <PermissionDialog
        open
        onOpenChange={jest.fn()}
        resourceType="channel"
        resourceId="channel-1"
        resourceName="Channel 1"
      />,
    );

    await waitFor(() => {
      expect(mockedGetGrantableRelationModels).toHaveBeenCalledTimes(1);
    });
    expect(mockedGetGrantableRelationModels).toHaveBeenCalledWith("channel", "channel-1");
    expect(screen.getByText("list:channel:channel-1:0")).toBeInTheDocument();
  });
});
