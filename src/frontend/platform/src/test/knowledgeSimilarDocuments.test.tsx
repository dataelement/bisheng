import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import {
  SimilarDocumentDialog,
  VersionManagementDialog,
  type SimilarDocumentCandidate,
  type SimilarDocumentFile,
  type SimilarDocumentsServices,
  type VersionLinkResult,
} from "@bisheng/knowledge";

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

function candidate(id = 61, title = "Recommended document"): SimilarDocumentCandidate {
  return { target_document_id: id, title, current_primary_version_no: 1, similarity: 0.98 };
}

function services() {
  return {
    getRecommendations: vi.fn<SimilarDocumentsServices["getRecommendations"]>().mockResolvedValue([candidate()]),
    searchDocuments: vi.fn<SimilarDocumentsServices["searchDocuments"]>().mockResolvedValue([]),
    relate: vi.fn<SimilarDocumentsServices["relate"]>().mockResolvedValue({ document_id: 41, new_version_no: 2 }),
    dismiss: vi.fn<SimilarDocumentsServices["dismiss"]>().mockResolvedValue(undefined),
  };
}

const file: SimilarDocumentFile = { id: 12, name: "Current document", version_no: 1, user_name: "Uploader" };

function singleProps(ports = services()) {
  return {
    open: true,
    onOpenChange: vi.fn(),
    spaceId: 7,
    file,
    services: ports,
    onLinked: vi.fn(),
    onDismissed: vi.fn(),
    onError: vi.fn(),
    onSuccess: vi.fn(),
  };
}

afterEach(cleanup);

it("submits search immediately and continues searching when the keyword changes", async () => {
  const props = singleProps();
  render(<VersionManagementDialog {...props} />);
  await screen.findByText("Recommended document");
  const input = screen.getByRole("textbox");
  fireEvent.change(input, { target: { value: "first" } });
  fireEvent.click(screen.getByRole("button", { name: "search_button" }));
  await waitFor(() => expect(props.services.searchDocuments).toHaveBeenCalledWith(7, "first", 12, expect.any(AbortSignal)));
  fireEvent.change(input, { target: { value: "second" } });
  await waitFor(() => expect(props.services.searchDocuments).toHaveBeenCalledWith(7, "second", 12, expect.any(AbortSignal)));
  fireEvent.change(input, { target: { value: "third" } });
  fireEvent.keyDown(input, { key: "Enter" });
  await waitFor(() => expect(props.services.searchDocuments).toHaveBeenCalledWith(7, "third", 12, expect.any(AbortSignal)));
});

it("keeps recommendation errors visible and retries the failed request", async () => {
  const props = singleProps();
  const error = new Error("Recommendations unavailable");
  props.services.getRecommendations.mockRejectedValueOnce(error).mockResolvedValueOnce([candidate()]);
  render(<VersionManagementDialog {...props} />);
  await waitFor(() => expect(props.onError).toHaveBeenCalledWith(error));
  expect(screen.getByRole("alert")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "retry" }));
  expect(await screen.findByText("Recommended document")).toBeInTheDocument();
  expect(props.services.getRecommendations).toHaveBeenCalledTimes(2);
});

it("retries search failures and discards results for an older keyword", async () => {
  const props = singleProps();
  const error = new Error("Search unavailable");
  const previous = deferred<Awaited<ReturnType<SimilarDocumentsServices["searchDocuments"]>>>();
  props.services.searchDocuments
    .mockRejectedValueOnce(error)
    .mockReturnValueOnce(previous.promise)
    .mockResolvedValue([{ document_id: 62, title: "Latest search result", current_primary_version_no: 1 }]);
  render(<VersionManagementDialog {...props} />);
  await screen.findByText("Recommended document");
  const input = screen.getByRole("textbox");
  fireEvent.change(input, { target: { value: "old" } });
  fireEvent.click(screen.getByRole("button", { name: "search_button" }));
  await waitFor(() => expect(props.onError).toHaveBeenCalledWith(error));
  fireEvent.click(screen.getByRole("button", { name: "retry" }));
  await waitFor(() => expect(props.services.searchDocuments).toHaveBeenCalledTimes(2));
  const previousSignal = props.services.searchDocuments.mock.calls[1][3];
  fireEvent.change(input, { target: { value: "new" } });
  fireEvent.click(screen.getByRole("button", { name: "search_button" }));
  expect(await screen.findByText("Latest search result")).toBeInTheDocument();
  expect(previousSignal?.aborted).toBe(true);
  await act(async () => { previous.resolve([{ document_id: 63, title: "Retired search result", current_primary_version_no: 1 }]); });
  expect(screen.queryByText("Retired search result")).not.toBeInTheDocument();
});

it("requires confirmation, submits one mutation, and locks dismissal until it completes", async () => {
  const props = singleProps();
  const mutation = deferred<VersionLinkResult>();
  props.services.relate.mockReturnValue(mutation.promise);
  render(<VersionManagementDialog {...props} />);
  const link = await screen.findByRole("button", { name: "btn_link_as_new_version" });
  const dismiss = screen.getByRole("button", { name: "btn_dismiss" });
  const close = screen.getByRole("button", { name: "close" });
  fireEvent.click(link);
  const firstConfirmation = await screen.findByRole("alertdialog");
  expect(firstConfirmation).toHaveTextContent("confirm_merge_description");
  fireEvent.click(within(firstConfirmation).getByRole("button", { name: "cancel" }));
  expect(props.services.relate).not.toHaveBeenCalled();
  fireEvent.click(link);
  const confirmation = await screen.findByRole("alertdialog");
  const confirm = within(confirmation).getByRole("button", { name: "confirm" });
  fireEvent.click(confirm);
  fireEvent.click(confirm);
  await waitFor(() => expect(props.services.relate).toHaveBeenCalledExactlyOnceWith(12, 61, expect.any(AbortSignal)));
  expect(dismiss).toBeDisabled();
  expect(close).toBeDisabled();
  await act(async () => { mutation.resolve({ document_id: 41, new_version_no: 2 }); });
  await waitFor(() => expect(props.onLinked).toHaveBeenCalledExactlyOnceWith({ document_id: 41, new_version_no: 2 }));
  expect(props.onSuccess).toHaveBeenCalledWith("toast_link_success");
});

it("dismisses without linking and reports completion to the host", async () => {
  const props = singleProps();
  render(<VersionManagementDialog {...props} />);
  fireEvent.click(await screen.findByRole("button", { name: "btn_dismiss" }));
  await waitFor(() => expect(props.onDismissed).toHaveBeenCalledTimes(1));
  expect(props.services.dismiss).toHaveBeenCalledExactlyOnceWith(12, expect.any(AbortSignal));
  expect(props.services.relate).not.toHaveBeenCalled();
  expect(props.onSuccess).toHaveBeenCalledWith("toast_dismiss_success");
});

it("blocks mutation replay when the server response leaves the result uncertain", async () => {
  const props = singleProps();
  const error = new Error("Response lost");
  props.services.relate.mockRejectedValueOnce(error);
  const view = render(<VersionManagementDialog {...props} />);
  fireEvent.click(await screen.findByRole("button", { name: "btn_link_as_new_version" }));
  fireEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "confirm" }));
  await waitFor(() => expect(props.onError).toHaveBeenCalledWith(error));
  const link = screen.getByRole("button", { name: "btn_link_as_new_version" });
  const dismiss = screen.getByRole("button", { name: "btn_dismiss" });
  expect(link).toBeDisabled();
  expect(dismiss).toBeDisabled();
  fireEvent.click(link);
  fireEvent.click(dismiss);
  expect(props.services.relate).toHaveBeenCalledTimes(1);
  expect(props.services.dismiss).not.toHaveBeenCalled();
  expect(props.onSuccess).not.toHaveBeenCalled();
  expect(screen.getByRole("button", { name: "close" })).toBeEnabled();
  view.rerender(<VersionManagementDialog {...props} open={false} />);
  view.rerender(<VersionManagementDialog {...props} />);
  const reopenedLink = await screen.findByRole("button", { name: "btn_link_as_new_version" });
  expect(reopenedLink).toBeEnabled();
  expect(props.services.relate).toHaveBeenCalledTimes(1);
});

it("retires an open confirmation and candidates when the services context changes", async () => {
  const props = singleProps();
  const view = render(<VersionManagementDialog {...props} />);
  fireEvent.click(await screen.findByRole("button", { name: "btn_link_as_new_version" }));
  await screen.findByRole("alertdialog");
  const nextServices = services();
  const recommendations = deferred<SimilarDocumentCandidate[]>();
  nextServices.getRecommendations.mockReturnValueOnce(recommendations.promise);
  view.rerender(<VersionManagementDialog {...props} services={nextServices} />);
  expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  expect(screen.queryByText("Recommended document")).not.toBeInTheDocument();
  expect(props.services.relate).not.toHaveBeenCalled();
  await act(async () => { recommendations.resolve([candidate(62, "New context recommendation")]); });
  expect(await screen.findByText("New context recommendation")).toBeInTheDocument();
  expect(nextServices.relate).not.toHaveBeenCalled();
});

it("discards old recommendations and pending mutation callbacks when the file changes", async () => {
  const props = singleProps();
  const previous = deferred<SimilarDocumentCandidate[]>();
  props.services.getRecommendations.mockReturnValueOnce(previous.promise).mockResolvedValueOnce([candidate(62, "New recommendation")]);
  const view = render(<VersionManagementDialog {...props} />);
  await waitFor(() => expect(props.services.getRecommendations).toHaveBeenCalledWith(12, expect.any(AbortSignal)));
  const signal = props.services.getRecommendations.mock.calls[0][1];
  view.rerender(<VersionManagementDialog {...props} file={{ ...file, id: 13, name: "New current document" }} />);
  expect(await screen.findByText("New recommendation")).toBeInTheDocument();
  expect(signal?.aborted).toBe(true);
  await act(async () => { previous.resolve([candidate(61, "Retired recommendation")]); });
  expect(screen.queryByText("Retired recommendation")).not.toBeInTheDocument();

  const mutation = deferred<VersionLinkResult>();
  props.services.relate.mockReturnValueOnce(mutation.promise);
  fireEvent.click(screen.getByRole("button", { name: "btn_link_as_new_version" }));
  fireEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "confirm" }));
  await waitFor(() => expect(props.services.relate).toHaveBeenCalledTimes(1));
  view.rerender(<VersionManagementDialog {...props} file={{ ...file, id: 14, name: "Another current document" }} />);
  await act(async () => { mutation.resolve({ document_id: 41, new_version_no: 2 }); });
  expect(props.onLinked).not.toHaveBeenCalled();
  expect(props.onSuccess).not.toHaveBeenCalled();
});

function pending(id: number) {
  return { knowledge_file_id: id, file_name: `Pending ${id}`, candidate_count: 1, current_primary_version_no: 1 };
}

it("restricts batch processing to the selected files and advances after dismissal", async () => {
  const props = singleProps();
  const ports = {
    ...props.services,
    getPending: vi.fn().mockResolvedValueOnce([pending(11), pending(12), pending(13)]).mockResolvedValue([pending(11), pending(13)]),
  };
  const processed = vi.fn();
  render(<SimilarDocumentDialog {...props} services={ports} restrictToFileIds={["12", "13"]} onProcessed={processed} />);
  await waitFor(() => expect(ports.getRecommendations).toHaveBeenCalledWith(12, expect.any(AbortSignal)));
  expect(screen.queryByRole("button", { name: /Pending 11/ })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: /Pending 12/ })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "btn_dismiss" }));
  await waitFor(() => expect(ports.getRecommendations).toHaveBeenCalledWith(13, expect.any(AbortSignal)));
  expect(processed).toHaveBeenCalledTimes(1);
  expect(ports.dismiss).toHaveBeenCalledExactlyOnceWith(12, expect.any(AbortSignal));
  fireEvent.click(await screen.findByRole("button", { name: "btn_link_as_new_version" }));
  const confirmation = await screen.findByRole("alertdialog");
  expect(confirmation).toHaveTextContent("confirm_link_description");
  fireEvent.click(within(confirmation).getByRole("button", { name: "confirm" }));
  await waitFor(() => expect(ports.relate).toHaveBeenCalledExactlyOnceWith(13, 61, expect.any(AbortSignal)));
  expect(processed).toHaveBeenCalledTimes(2);
});

it("ignores a pending-list response from a retired space", async () => {
  const props = singleProps();
  const previous = deferred<ReturnType<typeof pending>[]>();
  const ports = { ...props.services, getPending: vi.fn().mockReturnValueOnce(previous.promise).mockResolvedValue([pending(22)]) };
  const view = render(<SimilarDocumentDialog {...props} services={ports} />);
  await waitFor(() => expect(ports.getPending).toHaveBeenCalledWith(7, expect.any(AbortSignal)));
  const signal = ports.getPending.mock.calls[0][1] as AbortSignal;
  view.rerender(<SimilarDocumentDialog {...props} spaceId={8} services={ports} />);
  await screen.findByRole("button", { name: /Pending 22/ });
  expect(signal.aborted).toBe(true);
  await act(async () => { previous.resolve([pending(11)]); });
  expect(screen.queryByRole("button", { name: /Pending 11/ })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: /Pending 22/ })).toBeInTheDocument();
});
