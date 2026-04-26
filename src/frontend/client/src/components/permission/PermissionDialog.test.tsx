import { render, screen } from "@testing-library/react";

import { PermissionDialog } from "./PermissionDialog";

jest.mock("~/pages/knowledge/SpaceDetail/KnowledgeSpaceShareDialog", () => ({
  KnowledgeSpaceShareDialog: ({
    resourceType,
    resourceId,
    resourceName,
    showShareTab,
    showMembersTab,
    showPermissionTab,
  }: any) => (
    <div>
      {`share-dialog:${resourceType}:${resourceId}:${resourceName}:${showShareTab}:${showMembersTab}:${showPermissionTab}`}
    </div>
  ),
}));

describe("PermissionDialog", () => {
  it("uses the shared subject-scoped permission dialog", () => {
    render(
      <PermissionDialog
        open
        onOpenChange={jest.fn()}
        resourceType="channel"
        resourceId="channel-1"
        resourceName="Channel 1"
      />,
    );

    expect(
      screen.getByText("share-dialog:channel:channel-1:Channel 1:false:false:true"),
    ).toBeInTheDocument();
  });
});
