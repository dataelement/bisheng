/** @jest-environment node */

import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

function source(relativePath: string) {
  return readFileSync(join(process.cwd(), "src", relativePath), "utf8");
}

describe("F050 unified permission entry structure", () => {
  it("registers the four create/settings routes behind the existing plugin gates", () => {
    const routes = source("routes/index.tsx");

    expect(routes).toContain("path: 'knowledge/create'");
    expect(routes).toContain("path: 'knowledge/space/:spaceId/settings'");
    expect(routes).toContain("path: 'channel/create'");
    expect(routes).toContain("path: 'channel/:channelId/settings'");
    expect(routes).toContain('pluginId="knowledge_space"');
    expect(routes).toContain('pluginId="subscription"');
    expect(routes).toContain("default: module.KnowledgeSpaceSettingsPage");
    expect(routes).toContain("default: module.ChannelSettingsPage");
  });

  it("gives knowledge create and settings pages an inner scrolling shell", () => {
    const layout = source("layouts/MainLayout.tsx");

    expect(layout).toContain("path: '/knowledge/create'");
    expect(layout).toContain("path: '/knowledge/space/:spaceId/settings'");
    expect(layout).toContain("isKnowledgeSettingsRoute ||");
  });

  it("uses one settings callback and retains unrelated channel actions", () => {
    const articleMenu = source("pages/Subscription/ArticleList/ChannelActionsMenu.tsx");
    const sidebarItem = source("pages/Subscription/Sidebar/ChannelItem.tsx");

    for (const menu of [articleMenu, sidebarItem]) {
      expect(menu).toContain("onChannelSettings");
      expect(menu).not.toContain("onManageMembers");
      expect(menu).not.toContain("ChannelPermissionDialog");
      expect(menu).not.toContain("ChannelShareDialog");
    }
    expect(articleMenu).toContain("handleDeleteChannel");
    expect(articleMenu).toContain("handleUnsubscribeChannel");
    expect(articleMenu).toContain("onShare");
    expect(sidebarItem).toContain("onPin");
  });

  it("uses one space settings callback and retains pin, leave, and delete actions", () => {
    const listItem = source("pages/knowledge/sidebar/KnowledgeSpaceItem.tsx");
    const cardItem = source("pages/knowledge/sidebar/KnowledgeSpaceCardItem.tsx");
    const detail = source("pages/knowledge/SpaceDetail/index.tsx");
    const sidebar = source("pages/knowledge/sidebar/KnowledgeSpaceSidebar.tsx");

    for (const item of [listItem, cardItem]) {
      expect(item).toContain("onSettings");
      expect(item).not.toContain("onManageMembers");
    }
    expect(listItem).toContain("onPin");
    expect(listItem).toContain("onLeave");
    expect(listItem).toContain("onDelete");
    expect(detail).not.toContain('type: "folder" | "knowledge_file" | "knowledge_space"');
    expect(detail).not.toContain("const canManageMembers = isAdmin ||");
    expect(detail).not.toContain("const canEditSpace = isAdmin ||");
    expect(sidebar).not.toContain("const canManageMembers = isCreator ||");
    expect(sidebar).not.toContain("const canEditSpace = isCreator ||");
  });

  it("keeps generic file/folder permission UI while old resource-only dialogs are gone", () => {
    const detail = source("pages/knowledge/SpaceDetail/index.tsx");
    const permissionDialog = source("components/permission/PermissionDialog.tsx");

    expect(existsSync(join(process.cwd(), "src/pages/Subscription/ChannelPermissionDialog.tsx"))).toBe(false);
    expect(existsSync(join(process.cwd(), "src/pages/Subscription/ChannelShareDialog.tsx"))).toBe(false);
    expect(existsSync(join(process.cwd(), "src/pages/knowledge/CreateKnowledgeSpaceDrawer.tsx"))).toBe(false);
    expect(detail).toContain("KnowledgeSpaceShareDialog");
    expect(permissionDialog).toContain("resourceType");
    expect(permissionDialog).toContain("resourceId");
  });
});
