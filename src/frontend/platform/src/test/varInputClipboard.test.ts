import { describe, expect, it } from "vitest";

import { htmlClipboardToInsertable } from "@/pages/BuildPage/flow/FlowNode/component/varInputClipboard";

function toInsertable(html: string): string {
    const doc = new DOMParser().parseFromString(html, "text/html");
    return htmlClipboardToInsertable(doc.body);
}

describe("htmlClipboardToInsertable", () => {
    it("turns <br> into line breaks", () => {
        expect(toInsertable("line1<br>line2")).toBe("line1<br>line2");
    });

    it("keeps paragraph breaks from <p>", () => {
        expect(toInsertable("<p>line1</p><p>line2</p>")).toBe("line1<br>line2");
    });

    it("keeps one-div-per-line contentEditable copies", () => {
        expect(toInsertable("<div>line1</div><div>line2</div>")).toBe("line1<br>line2");
    });

    it("trims wrapper empty lines from leading and trailing <div><br></div>", () => {
        expect(
            toInsertable("<div><br></div><div>hello</div><div>world</div><div><br></div>"),
        ).toBe("hello<br>world");
    });

    it("trims a wrapping container that starts and ends with <br>", () => {
        expect(toInsertable("<div><br>line1<br>line2<br></div>")).toBe("line1<br>line2");
    });

    it("does not invent a newline for a single line", () => {
        expect(toInsertable("hello world")).toBe("hello world");
    });

    it("keeps a blank line in the middle", () => {
        expect(toInsertable("line1<br><br>line2")).toBe("line1<br><br>line2");
    });

    it("preserves variable badge markup", () => {
        expect(
            toInsertable('hello <span class="textarea-badge">LLM/output</span> world'),
        ).toBe('hello <span class="textarea-badge">LLM/output</span> world');
    });

    it("ignores pretty-print whitespace between block tags", () => {
        expect(toInsertable("<p>line1</p>\n<p>line2</p>")).toBe("line1<br>line2");
    });
});
