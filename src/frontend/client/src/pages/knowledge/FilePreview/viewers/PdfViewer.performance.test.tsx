import { act, render, waitFor } from "@testing-library/react";
import type * as pdfjsLib from "pdfjs-dist";
import { Sidebar } from "../Sidebar";
import { PdfViewer } from "./PdfViewer";

jest.mock("~/hooks", () => ({
    useLocalize: () => (key: string) => key,
}));

interface ObserverRecord {
    callback: IntersectionObserverCallback;
    options?: IntersectionObserverInit;
    targets: Set<Element>;
}

const observers: ObserverRecord[] = [];

class MockIntersectionObserver {
    private readonly record: ObserverRecord;

    constructor(callback: IntersectionObserverCallback, options?: IntersectionObserverInit) {
        this.record = { callback, options, targets: new Set() };
        observers.push(this.record);
    }

    observe = (target: Element) => this.record.targets.add(target);
    unobserve = (target: Element) => this.record.targets.delete(target);
    disconnect = () => this.record.targets.clear();
    takeRecords = () => [];
    root = null;
    rootMargin = "0px";
    thresholds = [0];
}

function createPdfDocument(numPages: number) {
    const renderCancel = jest.fn();
    const getPage = jest.fn(async () => ({
        getViewport: ({ scale }: { scale: number }) => ({
            width: 600 * scale,
            height: 800 * scale,
        }),
        render: () => ({ promise: Promise.resolve(), cancel: renderCancel }),
    }));
    return {
        document: { numPages, getPage } as unknown as pdfjsLib.PDFDocumentProxy,
        getPage,
    };
}

function revealPage(pageNumber: number, rootMargin: string) {
    const observer = observers.find((record) => (
        record.options?.rootMargin === rootMargin
        && [...record.targets].some((target) => target.getAttribute("data-page") === String(pageNumber))
    ));
    const target = observer && [...observer.targets].find(
        (element) => element.getAttribute("data-page") === String(pageNumber)
    );
    if (!observer || !target) throw new Error(`Observer for page ${pageNumber} not found`);

    act(() => {
        observer.callback([
            {
                target,
                isIntersecting: true,
                intersectionRatio: 1,
            } as IntersectionObserverEntry,
        ], observer as unknown as IntersectionObserver);
    });
}

describe("large PDF lazy rendering", () => {
    beforeAll(() => {
        Object.defineProperty(HTMLElement.prototype, "clientWidth", {
            configurable: true,
            get: () => 800,
        });
        Element.prototype.scrollIntoView = jest.fn();
        global.IntersectionObserver = MockIntersectionObserver as unknown as typeof IntersectionObserver;
    });

    beforeEach(() => observers.splice(0, observers.length));

    it("renders only nearby document pages until another page enters overscan", async () => {
        const { document, getPage } = createPdfDocument(100);
        render(
            <PdfViewer
                pdfDoc={document}
                zoomLevel={100}
                targetPage={null}
                onCurrentPageChange={jest.fn()}
            />
        );

        await waitFor(() => {
            expect(getPage).toHaveBeenCalledWith(1);
            expect(getPage).toHaveBeenCalledWith(2);
        });
        expect(getPage.mock.calls.map(([pageNumber]) => pageNumber).sort()).toEqual([1, 2]);

        revealPage(50, "1200px 0px");
        await waitFor(() => expect(getPage).toHaveBeenCalledWith(50));
    });

    it("renders only nearby thumbnails until the sidebar scrolls", async () => {
        const { document, getPage } = createPdfDocument(100);
        render(
            <Sidebar
                open
                pdfDoc={document}
                currentPage={1}
                onPageClick={jest.fn()}
            />
        );

        await waitFor(() => {
            expect(getPage).toHaveBeenCalledWith(1);
            expect(getPage).toHaveBeenCalledWith(3);
        });
        expect(getPage.mock.calls.map(([pageNumber]) => pageNumber).sort()).toEqual([1, 2, 3]);

        revealPage(50, "500px 0px");
        await waitFor(() => expect(getPage).toHaveBeenCalledWith(50));
    });
});
