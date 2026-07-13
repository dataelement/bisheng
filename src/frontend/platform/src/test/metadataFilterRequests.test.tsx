import type { InputHTMLAttributes, ReactNode } from "react";

import MetadataFilter from "@/pages/BuildPage/flow/FlowNode/component/MetadataFilter";
import { act, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const getKnowledgeDetailApi = vi.fn();
const translate = (key: string) => key;

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: translate }),
}));

vi.mock("@/controllers/API", () => ({
  getKnowledgeDetailApi: (...args: unknown[]) => getKnowledgeDetailApi(...args),
}));

vi.mock("@/components/bs-ui/select", () => ({
  Select: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  SelectContent: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  SelectItem: ({ children, value }: { children: ReactNode; value: string }) => (
    <div data-testid={`metadata-option-${value}`}>{children}</div>
  ),
  SelectTrigger: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  SelectValue: ({ children }: { children?: ReactNode }) => <div>{children}</div>,
}));

vi.mock("@/components/bs-ui/input", () => ({
  Input: (props: InputHTMLAttributes<HTMLInputElement>) => <input {...props} />,
}));

describe("MetadataFilter metadata loading", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("loads the same knowledge metadata only once across parent rerenders", async () => {
    let resolveKnowledgeDetails: (value: unknown[]) => void = () => {};
    getKnowledgeDetailApi.mockReturnValue(new Promise((resolve) => {
      resolveKnowledgeDetails = resolve;
    }));

    const data = { value: { enabled: true, conditions: [] } };
    const onChange = vi.fn();
    const onValidate = vi.fn();
    const renderFilter = () => (
      <MetadataFilter
        data={data}
        onChange={onChange}
        onValidate={onValidate}
        selectedKnowledgeIds={() => ["3726"]}
        i18nPrefix="node.knowledge.metadata_filter."
      />
    );

    const { rerender } = render(renderFilter());
    rerender(renderFilter());
    rerender(renderFilter());

    await waitFor(() => {
      expect(getKnowledgeDetailApi).toHaveBeenCalledTimes(1);
    });
    expect(getKnowledgeDetailApi).toHaveBeenCalledWith(["3726"]);

    await act(async () => {
      resolveKnowledgeDetails([]);
      await Promise.resolve();
    });
  });

  it("provides built-in metadata fields for knowledge spaces without requesting knowledge details", async () => {
    const data = {
      value: {
        enabled: true,
        operator: "and",
        conditions: [{
          id: "condition-1",
          knowledge_id: 9001,
          metadata_field: "document_name",
          comparison_operation: "equals",
          right_value_type: "input",
          right_value: "spec.pdf",
        }],
      },
    };
    const node = {
      name: "Knowledge retrieval",
      group_params: [{
        params: [{
          type: "knowledge_select_multi",
          value: {
            type: "space",
            value: [{ key: 9001, label: "Product knowledge space" }],
          },
        }],
      }],
    };

    render(
      <MetadataFilter
        data={data}
        node={node}
        onChange={vi.fn()}
        onValidate={vi.fn()}
        i18nPrefix="node.knowledge.metadata_filter."
      />,
    );

    const defaultFields = [
      "document_id",
      "document_name",
      "upload_time",
      "update_time",
      "uploader",
      "updater",
    ];
    await waitFor(() => {
      defaultFields.forEach((field) => {
        expect(screen.getByTestId(`metadata-option-9001-${field}`)).toBeInTheDocument();
      });
    });
    expect(getKnowledgeDetailApi).not.toHaveBeenCalled();
    expect(screen.queryByText("custom_metadata")).not.toBeInTheDocument();
  });
});
