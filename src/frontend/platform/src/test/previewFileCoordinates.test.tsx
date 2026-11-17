import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import PreviewFile from "@/pages/KnowledgePage/components/PreviewFile";
import useKnowledgeStore from "@/pages/KnowledgePage/useKnowledgeStore";

// Observe the PDF boundary without loading a browser PDF worker.
vi.mock("@/components/bs-comp/FileView", () => ({
  default: ({ labels, scrollTo }: { labels: unknown; scrollTo: unknown }) => (
    <output data-testid="pdf">{JSON.stringify({ labels, scrollTo })}</output>
  ),
}));
vi.mock("@/controllers/API", () => ({}));
vi.mock("@/controllers/request", () => ({ default: {}, showApiError: vi.fn() }));
vi.mock("@/pages/KnowledgePage/components/DocxFileViewer", () => ({ default: () => null }));
vi.mock("@/pages/KnowledgePage/components/TxtFileViewer", () => ({ default: () => null }));
vi.mock("@/pages/KnowledgePage/components/Guide", () => ({ default: () => null }));
vi.mock("@/pages/KnowledgePage/components/Markdown", () => ({ default: () => null }));
vi.mock("@/pages/KnowledgePage/components/RichPreviewFile", () => ({
  default: () => null, isRichKnowledgePreview: () => false,
}));

const file = { id: 98203, name: "source.pdf", suffix: "pdf", fileType: "mineru_v4" };
const partitions = {
  "0-35-29-77-127": { text: "Source text", type: "Text", part_id: "1" },
};
const chunks = [{
  chunkIndex: 0, text: "Source text",
  bbox: JSON.stringify({ chunk_bboxes: [{ page: 0, bbox: [35, 29, 77, 127] }] }),
}];
const props = {
  file, rawFiles: [file], chunks, step: 3, setChunks: vi.fn(),
  urlState: { load: true, url: "https://files.example/source.pdf" },
};
function pdf() {
  return JSON.parse(screen.getByTestId("pdf").textContent ?? "{}");
}
beforeEach(() => useKnowledgeStore.setState({ selectedChunkIndex: -1, selectedChunkDistanceFactor: 0 }));
afterEach(cleanup);

it("highlights and locates a chunk when coordinates arrive after the preview mounts", () => {
  const view = render(<PreviewFile {...props} partitions={{}} />);
  view.rerender(<PreviewFile {...props} partitions={partitions} />);
  act(() => useKnowledgeStore.getState().setSelectedChunkIndex(0));
  expect(pdf().labels[0]).toEqual([
    { id: "0-35-29-77-127", page: 0, label: [35, 29, 77, 127], txt: "Source text", active: true },
  ]);
  expect(pdf().scrollTo).toEqual([0, 29]);
});

it("updates the selected chunk when its coordinates finish loading", () => {
  const view = render(<PreviewFile {...props} partitions={{}} />);
  act(() => useKnowledgeStore.getState().setSelectedChunkIndex(0));
  view.rerender(<PreviewFile {...props} partitions={partitions} />);
  expect(pdf().labels[0]?.[0]?.active).toBe(true);
  expect(pdf().scrollTo).toEqual([0, 29]);
});

it("removes old overlays when coordinate data is replaced with an empty result", () => {
  const view = render(<PreviewFile {...props} partitions={partitions} />);
  act(() => useKnowledgeStore.getState().setSelectedChunkIndex(0));
  expect(pdf().labels[0]?.[0]?.active).toBe(true);
  view.rerender(<PreviewFile {...props} partitions={{}} />);
  expect(pdf().labels).toEqual({});
  expect(pdf().scrollTo).toEqual([0, 0]);
});
