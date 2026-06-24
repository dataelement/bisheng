import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { readFileLibDatabase } from "@/controllers/API";
import { getAuthorizedKnowledgeSpaceOptionsApi } from "@/controllers/API/knowledgeSpace";
import KnowledgeQaSelectItem from "@/pages/BuildPage/flow/FlowNode/component/KnowledgeQaSelectItem";
import KnowledgeSelectItem from "@/pages/BuildPage/flow/FlowNode/component/KnowledgeSelectItem";

vi.mock("@/controllers/API", () => ({
  getKnowledgeDetailApi: vi.fn(),
  readFileLibDatabase: vi.fn(),
}));

vi.mock("@/controllers/API/knowledgeSpace", () => ({
  getAuthorizedKnowledgeSpaceOptionsApi: vi.fn(),
}));

vi.mock("@/pages/BuildPage/flow/flowStore", () => ({
  default: () => ({ flow: { nodes: [] } }),
}));

vi.mock("@/components/bs-ui/select/multi", () => ({
  default: ({ onLoad, onScrollLoad }: any) => (
    <button
      type="button"
      onClick={() => {
        onLoad?.();
        onScrollLoad?.("");
      }}
    >
      open selector
    </button>
  ),
}));

const mockedReadFileLibDatabase = vi.mocked(readFileLibDatabase);
const mockedGetAuthorizedKnowledgeSpaceOptionsApi = vi.mocked(getAuthorizedKnowledgeSpaceOptionsApi);

const pendingSpacesRequest = () => new Promise<any>(() => {});

describe("workflow knowledge-space selector loading", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedReadFileLibDatabase.mockResolvedValue({
      data: [],
      next_cursor: null,
      has_more: false,
    } as any);
    mockedGetAuthorizedKnowledgeSpaceOptionsApi.mockImplementation(pendingSpacesRequest);
  });

  it("does not request page 2 when reopening document retrieval selector on space tab", async () => {
    render(
      <KnowledgeSelectItem
        data={{
          value: { type: "space", value: [{ key: 12, label: "Space" }] },
          required: false,
          placeholder: true,
        }}
        nodeId="node-1"
        onChange={vi.fn()}
        onVarEvent={vi.fn()}
        onValidate={vi.fn()}
        i18nPrefix="node.knowledge_retriever.knowledge."
      />,
    );

    await waitFor(() => {
      expect(mockedGetAuthorizedKnowledgeSpaceOptionsApi).toHaveBeenCalledTimes(1);
    });
    mockedGetAuthorizedKnowledgeSpaceOptionsApi.mockClear();

    fireEvent.click(screen.getByText("open selector"));

    expect(mockedGetAuthorizedKnowledgeSpaceOptionsApi).toHaveBeenCalledTimes(1);
    expect(mockedGetAuthorizedKnowledgeSpaceOptionsApi).toHaveBeenCalledWith({
      page: 1,
      page_size: 60,
      keyword: "",
      order_by: "name",
    });
  });

  it("does not request page 2 when reopening QA retrieval selector on space tab", async () => {
    render(
      <KnowledgeQaSelectItem
        data={{
          value: { type: "space", value: [{ key: 12, label: "Space" }] },
          required: false,
        }}
        nodeId="node-1"
        onChange={vi.fn()}
        onVarEvent={vi.fn()}
        onValidate={vi.fn()}
        i18nPrefix="node.qa_retriever.qa_knowledge_id."
      />,
    );

    await waitFor(() => {
      expect(mockedGetAuthorizedKnowledgeSpaceOptionsApi).toHaveBeenCalledTimes(1);
    });
    mockedGetAuthorizedKnowledgeSpaceOptionsApi.mockClear();

    fireEvent.click(screen.getByText("open selector"));

    expect(mockedGetAuthorizedKnowledgeSpaceOptionsApi).toHaveBeenCalledTimes(1);
    expect(mockedGetAuthorizedKnowledgeSpaceOptionsApi).toHaveBeenCalledWith({
      page: 1,
      page_size: 60,
      keyword: "",
      order_by: "name",
    });
  });
});
