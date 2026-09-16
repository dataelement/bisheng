/**
 * The review face reads 200 envelopes, so every refusal is a business code the
 * caller has to pull out itself — and the copy the user reads has to come from
 * `api_errors`, not from the backend's own Chinese `status_message`
 * (`utils/apiStatusError` exists because that mistake shipped once already).
 */

import { translateApiErrorMessage } from "~/api/request";
import request from "~/api/request";
import {
  getReviewContextApi,
  getSnapshotFileApi,
  getSnapshotTreeApi,
  getVersionDiffApi,
} from "./hostedAppReview";

jest.mock("~/api/request", () => ({
  __esModule: true,
  default: { get: jest.fn() },
  translateApiErrorMessage: jest.fn(),
}));

const get = (request as unknown as { get: jest.Mock }).get;
const translate = translateApiErrorMessage as unknown as jest.Mock;

beforeEach(() => {
  get.mockReset();
  translate.mockReset();
});

describe("the review reads", () => {
  it("unwraps the envelope and asks the endpoint the review view needs", async () => {
    get.mockResolvedValue({ status_code: 200, status_message: "SUCCESS", data: { role: "approver" } });

    await expect(getReviewContextApi("app-1", "ver-2")).resolves.toEqual({ role: "approver" });
    expect(get).toHaveBeenCalledWith("/api/v1/apps/app-1/versions/ver-2/review-context");
  });

  it("escapes the path so a file name can never be read as more URL", async () => {
    get.mockResolvedValue({ status_code: 200, status_message: "SUCCESS", data: {} });

    await getSnapshotFileApi("app 1", "ver/2", "src/a b.py?x=1");

    expect(get).toHaveBeenCalledWith(
      "/api/v1/apps/app%201/versions/ver%2F2/snapshot/file?path=src%2Fa%20b.py%3Fx%3D1",
    );
  });

  it("orders the diff old side first — AC-41 compares the published version to the pending one", async () => {
    get.mockResolvedValue({ status_code: 200, status_message: "SUCCESS", data: {} });

    await getVersionDiffApi("app-1", "ver-1", "ver-2");

    expect(get).toHaveBeenCalledWith("/api/v1/apps/app-1/versions/ver-1/diff/ver-2");
  });

  it("turns a business code into an error carrying the api_errors copy, not the backend sentence", async () => {
    translate.mockReturnValue("You do not have permission to view the source of this version");
    get.mockResolvedValue({
      status_code: 16257,
      // Stands for the backend's own zh-only sentence; the assertion is that it
      // is NOT what reaches the screen. (Written in ASCII: the lint rule bans
      // Chinese literals in source, tests included.)
      status_message: "<backend zh-only sentence>",
      data: { reason: "not_reviewer" },
    });

    await expect(getSnapshotTreeApi("app-1", "ver-2")).rejects.toMatchObject({
      status_code: 16257,
      message: "You do not have permission to view the source of this version",
    });
    expect(translate).toHaveBeenCalledWith(
      expect.objectContaining({ status_code: 16257 }),
    );
  });

  it("still fails closed when nothing translates the code", async () => {
    translate.mockReturnValue("");
    get.mockResolvedValue({ status_code: 16256, status_message: "", data: null });

    // Never resolves with an empty payload: a caller that renders whatever came
    // back would show an empty file tree as though the package held no files.
    await expect(getSnapshotTreeApi("app-1", "ver-2")).rejects.toThrow(/16256/);
  });
});
