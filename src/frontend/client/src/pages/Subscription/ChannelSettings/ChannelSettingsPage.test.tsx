import { fireEvent, render, screen } from "@testing-library/react";
import type { ButtonHTMLAttributes } from "react";
import { ChannelSettingsPage } from "./ChannelSettingsPage";
import {
  buildChannelSettingsUpdatePayload,
  type CreateChannelFormData,
} from "../channelUtils";

const mockShowToast = jest.fn();
const mockConfirm = jest.fn().mockResolvedValue(true);
const mockSetVisibility = jest.fn();
const mockReplaceRows = jest.fn();
const mockSubmit = jest
  .fn()
  .mockResolvedValue({ status: "success", channelId: "channel-1" });
const mockRetryAuthorization = jest.fn();
const mockEnterCreatedChannel = jest.fn();
const mockCancel = jest.fn();
const mockPermissionPickerRender = jest.fn();
let mockParams: { channelId?: string } = {};

const mockBusiness = {
  sources: [{ id: "source-1", name: "Source one", type: "website" }],
  setSources: jest.fn(),
  channelName: "Existing channel",
  setChannelName: jest.fn(),
  channelDesc: "Existing description",
  setChannelDesc: jest.fn(),
  visibility: "review" as const,
  setVisibility: mockSetVisibility,
  publishToSquare: "yes" as const,
  setPublishToSquare: jest.fn(),
  contentFilter: false,
  filterGroups: [],
  setFilterGroups: jest.fn(),
  topFilterRelation: "and" as const,
  setTopFilterRelation: jest.fn(),
  createSubChannel: false,
  subChannels: [],
  setSubChannels: jest.fn(),
  showAddSourcePanel: false,
  setShowAddSourcePanel: jest.fn(),
  sourceSearchResetToken: 0,
  handleContentFilterToggle: jest.fn(),
  handleCreateSubChannelToggle: jest.fn(),
  handleAddSubChannel: jest.fn(),
  handleRemoveSubChannel: jest.fn(),
  handleSubChannelNameChange: jest.fn(),
  handleSubChannelToggleCollapse: jest.fn(),
  handleSubChannelGroupsChange: jest.fn(),
  lastAddedSubChannelId: null,
  setLastAddedSubChannelId: jest.fn(),
};

const mockSettings = {
  localize: (key: string) => key,
  isEditMode: false,
  isLoading: false,
  loadError: null,
  business: mockBusiness,
  formData: {
    sources: mockBusiness.sources,
    channelName: mockBusiness.channelName,
    channelDesc: mockBusiness.channelDesc,
    visibility: "review" as const,
    publishToSquare: "yes" as const,
    contentFilter: false,
    filterGroups: [],
    topFilterRelation: "and" as const,
    createSubChannel: false,
    subChannels: [],
    knowledgeSync: { main: { enabled: false, spaces: [] }, subs: [] },
  },
  knowledgeSync: { main: { enabled: false, spaces: [] }, subs: [] },
  setKnowledgeSync: jest.fn(),
  canEditBusiness: true,
  canManagePermissions: true,
  isChannelCreator: true,
  showPermissionSection: true,
  relationModels: [
    { id: "viewer-model", name: "Viewer", relation: "viewer", is_system: true },
  ],
  permissionDraft: {
    rows: [
      {
        subjectType: "user",
        subjectId: 1,
        subjectName: "Creator",
        relation: "owner",
        immutableCreator: true,
      },
    ],
    replaceRows: mockReplaceRows,
    addRows: jest.fn(),
  },
  submitting: false,
  authorizationRecovery: null as null | {
    channelId: string;
    grants: [];
    errorCode: number | null;
  },
  submit: mockSubmit,
  retryAuthorization: mockRetryAuthorization,
  enterCreatedChannel: mockEnterCreatedChannel,
  cancel: mockCancel,
};

jest.mock("react-router-dom", () => ({
  useParams: () => mockParams,
}));

jest.mock("@bisheng/ui", () => ({
  Button: (
    props: {
      loading?: boolean;
      color?: string;
      variant?: string;
      size?: string;
    } & ButtonHTMLAttributes<HTMLButtonElement>,
  ) => {
    const buttonProps = { ...props };
    delete buttonProps.loading;
    delete buttonProps.color;
    delete buttonProps.variant;
    delete buttonProps.size;
    return <button {...buttonProps} />;
  },
}));

jest.mock("~/Providers", () => ({
  useToastContext: () => ({ showToast: mockShowToast }),
  useConfirm: () => mockConfirm,
}));

jest.mock("~/hooks", () => ({
  useLocalize: () => (key: string) => key,
  useAuthContext: () => ({
    user: {
      id: 99,
      name: "Current user",
      username: "current",
      email: "current@example.com",
    },
  }),
}));

jest.mock("./useChannelSettingsForm", () => ({
  useChannelSettingsForm: () => mockSettings,
}));

jest.mock("../hooks/useCrawlQueue", () => ({
  useCrawlQueue: () => ({
    queue: [],
    inProgressCount: 0,
    panelOpen: false,
    setPanelOpen: jest.fn(),
    abort: jest.fn(),
    enqueue: jest.fn(),
  }),
}));

jest.mock("../CreateChannel/AddSourceDropdown", () => ({
  AddSourceDropdown: () => <div data-testid="source-selector" />,
}));
jest.mock("../CreateChannel/CrawlQueuePanel", () => ({
  CrawlQueuePanel: () => null,
}));
jest.mock("../CreateChannel/CrawlPreviewDialog", () => ({
  CrawlPreviewDialog: () => null,
}));
jest.mock("../CreateChannel/CrawlFeedbackDialog", () => ({
  CrawlFeedbackDialog: () => null,
}));
jest.mock("../CreateChannel/FilterConditionEditor", () => ({
  FilterConditionEditor: () => <div data-testid="filter-editor" />,
}));
jest.mock("../CreateChannel/SubChannelBlock", () => ({
  SubChannelBlock: () => <div data-testid="sub-channel" />,
}));
jest.mock("../CreateChannel/KnowledgeSyncSection", () => ({
  __esModule: true,
  default: ({ isCreator }: { isCreator: boolean }) =>
    isCreator ? <div data-testid="knowledge-sync" /> : null,
}));
jest.mock("~/components/permission/PermissionDraftEditor", () => ({
  PermissionDraftEditor: ({ onChange }: { onChange: (rows: []) => void }) => (
    <button type="button" onClick={() => onChange([])}>
      draft-change
    </button>
  ),
}));
jest.mock("~/components/permission/PermissionDraftPickerDialog", () => ({
  PermissionDraftPickerDialog: (props: { searchApi?: unknown }) => {
    mockPermissionPickerRender(props);
    return null;
  },
}));
jest.mock("~/components/permission/RelationSelect", () => ({
  RelationSelect: () => null,
}));
jest.mock("~/components/permission/SubjectSearchUser", () => ({
  SubjectSearchUser: () => null,
}));
jest.mock("~/components/permission/SubjectSearchDepartment", () => ({
  SubjectSearchDepartment: () => null,
}));
jest.mock("~/components/permission/SubjectSearchUserGroup", () => ({
  SubjectSearchUserGroup: () => null,
}));

describe("ChannelSettingsPage", () => {
  beforeEach(() => {
    mockPermissionPickerRender.mockClear();
    mockParams = {};
    Object.assign(mockSettings, {
      isEditMode: false,
      isLoading: false,
      loadError: null,
      canEditBusiness: true,
      canManagePermissions: true,
      isChannelCreator: true,
      showPermissionSection: true,
      authorizationRecovery: null,
      submitting: false,
    });
    Object.assign(mockBusiness, {
      visibility: "review",
      publishToSquare: "yes",
      contentFilter: false,
      createSubChannel: false,
      subChannels: [],
    });
  });

  it("keeps channel and sub-channel filter surfaces white", () => {
    Object.assign(mockBusiness, {
      contentFilter: true,
      createSubChannel: true,
      subChannels: [
        {
          id: "sub-1",
          name: "Sub channel",
          collapsed: false,
          groups: [],
          topRelation: "and",
        },
      ],
    });

    render(<ChannelSettingsPage />);

    expect(
      screen.getByTestId("channel-filter-conditions").className,
    ).toContain("bg-white");
    expect(screen.getByTestId("sub-channel-list").className).toContain(
      "bg-white",
    );
  });

  it("renders preserved channel fields in a responsive two-column settings layout", () => {
    render(<ChannelSettingsPage />);

    expect(screen.getByDisplayValue("Existing channel")).not.toBeNull();
    expect(screen.getByDisplayValue("Existing description")).not.toBeNull();
    expect(screen.getByDisplayValue("Existing channel").className).toContain(
      "bg-white",
    );
    expect(
      screen.getByDisplayValue("Existing description").className,
    ).toContain("bg-white");
    expect(screen.getByTestId("source-selector")).not.toBeNull();
    expect(screen.getByTestId("knowledge-sync")).not.toBeNull();
    const businessColumn = screen.getByTestId("channel-business-column");
    const settingsSurface = businessColumn.closest("main");
    expect(settingsSurface?.className).toContain("w-full");
    expect(settingsSurface?.className).not.toContain("max-w-[1368px]");
    expect(settingsSurface?.className).not.toContain("rounded-xl");
    expect(settingsSurface?.parentElement?.className).not.toContain("p-2");
    expect(businessColumn.parentElement?.className).toContain("grid-cols-2");
    expect(businessColumn.parentElement?.className).toContain(
      "max-[900px]:grid-cols-1",
    );
    expect(screen.getByTestId("authorization-list-body").className).toContain(
      "h-[400px]",
    );
    expect(
      screen.getByRole("button", {
        name: "com_unified_permission.add_authorization",
      }).className,
    ).toContain("h-7");

    fireEvent.click(screen.getByText("draft-change"));
    expect(mockReplaceRows).toHaveBeenCalledWith([]);

    fireEvent.click(
      screen.getByRole("button", { name: "com_permission.subject_department" }),
    );
    expect(
      screen.getByRole("img", { name: "com_subscription.no_data" }),
    ).not.toBeNull();
  });

  it("hides access and authorization content for an edit-only collaborator", () => {
    mockParams = { channelId: "channel-1" };
    Object.assign(mockSettings, {
      isEditMode: true,
      canEditBusiness: true,
      canManagePermissions: false,
      showPermissionSection: false,
    });

    render(<ChannelSettingsPage />);

    expect(screen.getByTestId("channel-business-column")).not.toBeNull();
    expect(screen.queryByTestId("channel-permission-column")).toBeNull();
  });

  it("keeps edit-mode permission search adapters stable across rerenders", () => {
    mockParams = { channelId: "channel-1" };
    Object.assign(mockSettings, { isEditMode: true });

    const view = render(<ChannelSettingsPage />);
    const firstSearchApi = mockPermissionPickerRender.mock.calls.at(-1)?.[0]
      .searchApi;

    view.rerender(<ChannelSettingsPage />);

    const secondSearchApi = mockPermissionPickerRender.mock.calls.at(-1)?.[0]
      .searchApi;
    expect(firstSearchApi).toBeDefined();
    expect(secondSearchApi).toBe(firstSearchApi);
  });

  it("does not expose creator-only knowledge sync to a granted owner", () => {
    mockParams = { channelId: "channel-1" };
    Object.assign(mockSettings, { isEditMode: true, isChannelCreator: false });

    render(<ChannelSettingsPage />);

    expect(screen.queryByTestId("knowledge-sync")).toBeNull();
  });

  it("omits creator-only knowledge sync from a non-creator update payload", () => {
    const payload = buildChannelSettingsUpdatePayload(
      mockSettings.formData as CreateChannelFormData,
      false,
    );

    expect(payload).not.toHaveProperty("knowledge_sync");
  });

  it("hides share-only controls while private and defaults back to review when shared", () => {
    Object.assign(mockBusiness, {
      visibility: "private",
      publishToSquare: "no",
    });
    render(<ChannelSettingsPage />);

    expect(screen.queryByText("draft-change")).toBeNull();
    expect(
      screen.queryByText("com_unified_permission.publish_to_square"),
    ).toBeNull();

    fireEvent.click(
      screen.getByRole("radio", {
        name: /com_unified_permission\.shared/,
      }),
    );
    expect(mockSetVisibility).toHaveBeenCalledWith("review");
  });

  it("offers permission-only recovery without submitting resource creation again", () => {
    Object.assign(mockSettings, {
      authorizationRecovery: {
        channelId: "channel-1",
        grants: [],
        errorCode: 5001,
      },
    });
    render(<ChannelSettingsPage />);

    fireEvent.click(
      screen.getByText("com_unified_permission.retry_permission"),
    );
    fireEvent.click(screen.getByText("com_unified_permission.enter_channel"));

    expect(mockRetryAuthorization).toHaveBeenCalledTimes(1);
    expect(mockEnterCreatedChannel).toHaveBeenCalledTimes(1);
    expect(mockSubmit).not.toHaveBeenCalled();
  });

  it("submits the unified form once from the fixed action footer", () => {
    render(<ChannelSettingsPage />);

    fireEvent.click(screen.getByText("com_unified_permission.confirm_create"));
    expect(mockSubmit).toHaveBeenCalledTimes(1);
  });
});
