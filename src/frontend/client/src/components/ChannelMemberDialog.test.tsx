import { render, screen } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import type { Channel } from "~/api/channels";
import { ChannelPermissionDialog } from "~/pages/Subscription/ChannelPermissionDialog";

jest.mock("~/components/permission/PermissionDialog", () => ({
  PermissionDialog: ({
    resourceType,
    resourceId,
    resourceName,
  }: {
    resourceType: string;
    resourceId: string;
    resourceName: string;
  }) => (
    <div>
      {resourceType}:{resourceId}:{resourceName}
    </div>
  ),
}));

const channel = {
  id: "channel-1",
  name: "Engineering",
} as Channel;

describe("F048 Client channel permission entry", () => {
  it("reuses the F048 channel dialog and stable resource identity", () => {
    render(
      <ChannelPermissionDialog
        open
        onOpenChange={jest.fn()}
        channel={channel}
      />,
    );

    expect(
      screen.getByText("channel:channel-1:Engineering"),
    ).toBeInTheDocument();
  });

  it("contains no relation-model selector or relation payload adapter", () => {
    const dialogSource = readFileSync(
      resolve(
        process.cwd(),
        "src/pages/Subscription/ChannelPermissionDialog.tsx",
      ),
      "utf8",
    );

    expect(dialogSource).not.toMatch(
      /RelationSelect|RelationModel|authorizeChannelApi|relation:/,
    );

    const apiSource = readFileSync(
      resolve(process.cwd(), "src/api/channels.ts"),
      "utf8",
    );
    expect(apiSource).not.toMatch(
      /ChannelRelation|ChannelUserRole|item\.relation/,
    );
  });
});
