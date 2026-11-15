import { fireEvent, render, screen } from "@testing-library/react";
import { ChatKnowledge } from "./ChatKnowledge";
import { KnowledgeSpaceSelect } from "../../Linsight/Input/KnowledgeSpaceSelect";

let mockError = false;
let mockSpaces = [{ id: "41", name: "Directly authorized" }];
const mockLoadMore = jest.fn();
const mockRetry = jest.fn();
const mockCandidate = jest.fn();
jest.mock("~/hooks/useVisibleKnowledgeSpaces", () => ({
  useVisibleKnowledgeSpaces: (options) => {
    mockCandidate(options);
    return {
      spaces: mockSpaces,
      isFetching: false,
      isError: mockError,
      hasMore: true,
      loadMore: mockLoadMore,
      retry: mockRetry,
    };
  },
}));
jest.mock("~/hooks", () => ({
  useLocalize: () => (key: string) => key,
  useMediaQuery: () => false,
  useScrollRevealRef: () => () => {},
}));
jest.mock("~/hooks/queries/data-provider", () => ({
  useGetBsConfig: () => ({ data: { knowledgeBase: { enabled: true } } }),
  useGetOrgToolList: () => ({
    data: [{ id: "qa", name: "Independent QA" }],
    isFetching: false,
  }),
  useGetOrgToolPages: () => ({
    data: { pages: [] },
    isFetching: false,
    hasNextPage: false,
  }),
}));
jest.mock("~/Providers", () => ({
  useToastContext: () => ({ showToast: jest.fn() }),
}));
jest.mock("~/utils", () => ({
  cn: (...values) => values.filter((v) => typeof v === "string").join(" "),
}));
jest.mock("~/components/Skills/SkillMenuEntries", () => ({
  SkillUploadHost: ({ children }) => children(jest.fn()),
  SkillMenuEntries: () => null,
}));
jest.mock("~/components/Skills/SkillMenuPanel", () => ({
  SkillMenuPanel: () => null,
}));
jest.mock("bisheng-icons", () => ({
  Outlined: new Proxy({}, { get: () => () => null }),
}));
jest.mock("@bisheng/ui", () => ({
  Tooltip: ({ children }) => children,
  TooltipProvider: ({ children }) => children,
  SearchInput: ({ clearLabel, ...props }) => {
    void clearLabel;
    return <input {...props} />;
  },
  Checkbox: ({ checked }) => (
    <input type="checkbox" checked={checked} readOnly />
  ),
  StateView: ({ title }) => <span>{title}</span>,
  Button: ({ color, variant, loading, ...props }) => {
    void color;
    void variant;
    void loading;
    return <button {...props} />;
  },
}));
jest.mock("~/components/ui", () => {
  const React = jest.requireActual<typeof import("react")>("react");
  const Wrapper = React.forwardRef<
    HTMLDivElement,
    { children?: import("react").ReactNode }
  >(({ children }, ref) => <div ref={ref}>{children}</div>);
  return {
    DropdownMenu: ({ children, onOpenChange }) => (
      <div>
        <button onClick={() => onOpenChange(true)}>open picker</button>
        {children}
      </div>
    ),
    DropdownMenuTrigger: Wrapper,
    DropdownMenuContent: Wrapper,
    DropdownMenuSub: Wrapper,
    DropdownMenuSubTrigger: Wrapper,
    DropdownMenuSubContent: Wrapper,
    DropdownMenuItem: ({ children, onSelect }) => (
      <button onClick={() => onSelect({ preventDefault() {} })}>
        {children}
      </button>
    ),
  };
});
beforeEach(() => {
  mockError = false;
  mockSpaces = [{ id: "41", name: "Directly authorized" }];
});
const saved = {
  id: "999",
  name: "Saved outside this page",
  type: "space" as const,
};

test.each(["daily", "task"])(
  "%s actual selector keeps selection and exposes visible continuation",
  (variant) => {
    const onChange = jest.fn();
    render(
      variant === "daily" ? (
        <ChatKnowledge
          variant="knowledge"
          value={[saved]}
          onChange={onChange}
          disabled={false}
        />
      ) : (
        <KnowledgeSpaceSelect value={[saved]} onChange={onChange} />
      ),
    );
    fireEvent.click(screen.getByText("open picker"));
    expect(mockCandidate).toHaveBeenLastCalledWith(
      expect.objectContaining({ enabled: true }),
    );
    expect(onChange).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText("dshChat.loadMoreKnowledge"));
    expect(mockLoadMore).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByText("Directly authorized"));
    expect(onChange).toHaveBeenCalledWith(
      expect.arrayContaining([
        saved,
        { id: "41", name: "Directly authorized", type: "space" },
      ]),
    );
    if (variant === "task")
      expect(screen.getByText("Independent QA")).toBeInTheDocument();
  },
);

test.each(["daily", "task"])(
  "%s empty nonterminal failure has a real retry instead of deleting selection",
  (variant) => {
    mockError = true;
    mockSpaces = [];
    const onChange = jest.fn();
    render(
      variant === "daily" ? (
        <ChatKnowledge
          variant="knowledge"
          value={[saved]}
          onChange={onChange}
          disabled={false}
        />
      ) : (
        <KnowledgeSpaceSelect value={[saved]} onChange={onChange} />
      ),
    );
    expect(screen.getByRole("alert")).toBeInTheDocument();
    fireEvent.click(screen.getByText("dshChat.retryKnowledge"));
    expect(mockRetry).toHaveBeenCalledTimes(1);
    expect(onChange).not.toHaveBeenCalled();
  },
);
