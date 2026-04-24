import type { ReactNode } from "react";

import { userContext } from "@/contexts/userContext";
import { render, screen } from "@/test/test-utils";
import { fireEvent } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { loadNamespaces: vi.fn() },
  }),
}));

vi.mock("@/components/bs-icons/knowledge", () => ({
  BookIcon: () => <span data-testid="book-icon" />,
  QaIcon: () => <span data-testid="qa-icon" />,
}));

vi.mock("@/components/bs-icons/loading", () => ({
  LoadIcon: () => <span />,
  LoadingIcon: () => <span />,
}));

vi.mock("@/components/bs-ui/alertDialog/useConfirm", () => ({
  bsConfirm: vi.fn(),
}));

vi.mock("@/components/bs-ui/button", () => ({
  Button: ({ children, ...props }: any) => <button {...props}>{children}</button>,
}));

vi.mock("@/components/bs-ui/dialog", () => ({
  Dialog: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  DialogClose: ({ children }: { children: ReactNode }) => <>{children}</>,
  DialogContent: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  DialogFooter: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  DialogHeader: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  DialogTitle: ({ children }: { children: ReactNode }) => <div>{children}</div>,
}));

vi.mock("@/components/bs-ui/input", async () => {
  const React = await import("react");

  return {
    Input: React.forwardRef<HTMLInputElement, any>((props, ref) => <input ref={ref} {...props} />),
    SearchInput: (props: any) => <input aria-label="search" {...props} />,
    Textarea: React.forwardRef<HTMLTextAreaElement, any>((props, ref) => <textarea ref={ref} {...props} />),
  };
});

vi.mock("@/components/bs-ui/pagination/autoPagination", () => ({
  default: () => <div data-testid="pagination" />,
}));

vi.mock("@/components/bs-ui/table", () => ({
  Table: ({ children }: { children: ReactNode }) => <table>{children}</table>,
  TableBody: ({ children }: { children: ReactNode }) => <tbody>{children}</tbody>,
  TableCell: ({ children, ...props }: any) => <td {...props}>{children}</td>,
  TableHead: ({ children, ...props }: any) => <th {...props}>{children}</th>,
  TableHeader: ({ children }: { children: ReactNode }) => <thead>{children}</thead>,
  TableRow: ({ children, ...props }: any) => <tr {...props}>{children}</tr>,
}));

vi.mock("@/components/bs-ui/toast/use-toast", () => ({
  toast: vi.fn(),
  useToast: () => ({ message: vi.fn(), toast: vi.fn() }),
}));

vi.mock("@/components/bs-ui/tooltip", () => ({
  QuestionTooltip: ({ children }: { children: ReactNode }) => <>{children}</>,
}));

vi.mock("@/components/bs-ui/tooltip/tip", () => ({
  default: ({ children }: { children: ReactNode }) => <>{children}</>,
}));

vi.mock("lucide-react", () => ({
  CircleAlert: () => <span />,
  Copy: () => <span />,
  Ellipsis: () => <span />,
  LoaderCircle: () => <span />,
  Settings: () => <span />,
  Shield: () => <span />,
  Trash2: () => <span />,
}));

vi.mock("@/controllers/API", () => ({
  copyLibDatabase: vi.fn(),
  createFileLib: vi.fn(),
  deleteFileLib: vi.fn(),
  readFileLibDatabase: vi.fn(),
  updateKnowledge: vi.fn(),
}));

vi.mock("@/controllers/API/finetune", () => ({
  getKnowledgeModelConfig: vi.fn(),
}));

vi.mock("@/controllers/request", () => ({
  captureAndAlertRequestErrorHoc: vi.fn((promise: Promise<unknown>) => promise),
}));

vi.mock("@/pages/ModelPage/manage", () => ({
  useModel: () => ({ embeddings: [], isLoading: false }),
}));

vi.mock("@/pages/ModelPage/manage/tabs/WorkbenchModel", () => ({
  ModelSelect: () => <div />,
}));

vi.mock("@/components/bs-comp/permission/PermissionDialog", () => ({
  PermissionDialog: ({ open, onOpenChange, resourceName }: any) =>
    open ? (
      <div role="dialog">
        <span>{`permission:${resourceName}`}</span>
        <button type="button" onClick={() => onOpenChange(false)}>
          close-permission
        </button>
      </div>
    ) : null,
}));

vi.mock("@/components/bs-comp/permission/usePermissionLevels", () => ({
  canManageResource: () => true,
  usePermissionLevels: () => ({ levels: { "1": "owner" } }),
}));

vi.mock("@/util/hook", () => ({
  useTable: () => ({
    page: 1,
    pageSize: 20,
    data: [
      {
        id: 1,
        name: "知识库 A",
        description: "",
        update_time: "2026-04-24T10:00:00",
        user_id: 1,
        user_name: "admin",
        state: 1,
        copiable: true,
      },
    ],
    total: 1,
    loading: false,
    setPage: vi.fn(),
    search: vi.fn(),
    reload: vi.fn(),
  }),
}));

vi.mock("@/components/bs-ui/select", async () => {
  const React = await import("react");
  const SelectContext = React.createContext<any>(null);

  function Select({ children, onValueChange }: any) {
    const [value, setValue] = React.useState<string | null>(null);
    return (
      <SelectContext.Provider value={{ value, setValue, onValueChange }}>
        <div>{children}</div>
      </SelectContext.Provider>
    );
  }

  function SelectItem({ children, disabled, value }: any) {
    const ctx = React.useContext(SelectContext);
    return (
      <button
        type="button"
        disabled={disabled}
        onClick={() => {
          if (ctx.value === value) return;
          ctx.setValue(value);
          ctx.onValueChange(value);
        }}
      >
        {children}
      </button>
    );
  }

  return {
    Select,
    SelectContent: ({ children }: { children: ReactNode }) => <div>{children}</div>,
    SelectItem,
    SelectTrigger: ({ children, showIcon: _showIcon, ...props }: any) => <button {...props}>{children}</button>,
  };
});

const adminUser = {
  user_id: 1,
  user_name: "admin",
  role: "admin",
  web_menu: ["create_knowledge"],
};

describe("Knowledge library permission dialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("can reopen permission management after the dialog is closed", async () => {
    const { default: KnowledgeFile } = await import("@/pages/KnowledgePage/KnowledgeFile");

    render(
      <userContext.Provider value={{ user: adminUser } as any}>
        <KnowledgeFile />
      </userContext.Provider>,
    );

    const permissionMenuItem = screen.getByRole("button", { name: /managePermission/ });
    fireEvent.click(permissionMenuItem);
    expect(screen.getByRole("dialog")).toHaveTextContent("permission:知识库 A");

    fireEvent.click(screen.getByRole("button", { name: "close-permission" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /managePermission/ }));
    expect(screen.getByRole("dialog")).toHaveTextContent("permission:知识库 A");
  });
});
