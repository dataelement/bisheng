import JSZip from "jszip";

/**
 * Strips invisible zero-sized drawings from a .docx before mammoth reads it.
 *
 * Chinese e-seals (电子印章) park their signature payload inside a text box sized
 * `cx="0" cy="0"`. Word and WPS honour the empty extent and draw nothing, but mammoth
 * only looks for text and has no notion of shape geometry, so it spills the payload —
 * tens of thousands of base64 characters — into the document body as garbage.
 *
 * Removing those drawings takes two steps, because the seal is wrapped in an
 * `mc:AlternateContent` block that offers the same content twice: a modern `mc:Choice`
 * and a legacy `mc:Fallback`. mammoth honours that and renders only the Choice — but
 * emptying the Choice makes it fall back to the Fallback's copy, so the payload comes
 * straight back. We therefore flatten each block down to its Choice first (dropping the
 * Fallback escape hatch), then delete the zero-sized drawings.
 *
 * Only the parts that can carry body content are rewritten; the rest of the zip is
 * passed through untouched.
 *
 * Note this only hides the payload — it does not verify the seal. It also cannot fix
 * seals drawn as several images stacked at one anchor position: mammoth lays them out
 * sequentially because it ignores positioning, which needs a layout-aware renderer.
 */

const MC_NS = "http://schemas.openxmlformats.org/markup-compatibility/2006";

/** Parts whose XML can carry drawings; headers/footers hold seals just as often. */
const CONTENT_PART_PATTERN = /^word\/(document|header\d*|footer\d*)\.xml$/;

/** Replace each mc:AlternateContent with the children of its mc:Choice. */
function unwrapAlternateContent(doc: Document): number {
    const blocks = Array.from(doc.getElementsByTagNameNS(MC_NS, "AlternateContent"));
    let unwrapped = 0;
    for (const block of blocks) {
        const choice = Array.from(block.childNodes).find(
            (node): node is Element => node.nodeType === 1 && (node as Element).localName === "Choice",
        );
        const parent = block.parentNode;
        if (!parent) continue;
        // Without a Choice the block is Fallback-only; unwrapping nothing would drop
        // real content, so leave such a block alone.
        if (!choice) continue;
        while (choice.firstChild) parent.insertBefore(choice.firstChild, block);
        parent.removeChild(block);
        unwrapped += 1;
    }
    return unwrapped;
}

/** Delete drawings whose extent is 0x0 — invisible in Word, text-only to mammoth. */
function removeZeroSizedDrawings(doc: Document): number {
    const extents = Array.from(doc.getElementsByTagName("*")).filter((element) => (
        element.localName === "ext"
        && element.getAttribute("cx") === "0"
        && element.getAttribute("cy") === "0"
    ));
    let removed = 0;
    for (const extent of extents) {
        let node: Element | null = extent;
        while (node && node.localName !== "drawing") node = node.parentElement;
        if (node?.parentNode) {
            node.parentNode.removeChild(node);
            removed += 1;
        }
    }
    return removed;
}

export interface DocxSanitizeResult {
    arrayBuffer: ArrayBuffer;
    /** Zero means the file needed no repair; useful for diagnostics. */
    removedZeroSizedDrawings: number;
}

export async function sanitizeDocxForPreview(arrayBuffer: ArrayBuffer): Promise<DocxSanitizeResult> {
    const zip = await JSZip.loadAsync(arrayBuffer);
    const parser = new DOMParser();
    const serializer = new XMLSerializer();
    let removedZeroSizedDrawings = 0;

    for (const path of Object.keys(zip.files)) {
        if (!CONTENT_PART_PATTERN.test(path)) continue;
        const xml = await zip.files[path].async("string");
        const doc = parser.parseFromString(xml, "application/xml");
        // A malformed part would serialize back as an error document and destroy the
        // file; leave anything we can't parse exactly as it was.
        if (doc.getElementsByTagName("parsererror").length) continue;

        // Order matters: flatten first so removing the drawing can't be undone by
        // mammoth falling back to the Fallback copy.
        const unwrapped = unwrapAlternateContent(doc);
        const removed = removeZeroSizedDrawings(doc);
        if (!unwrapped && !removed) continue;

        removedZeroSizedDrawings += removed;
        zip.file(path, serializer.serializeToString(doc));
    }

    return {
        arrayBuffer: await zip.generateAsync({ type: "arraybuffer" }),
        removedZeroSizedDrawings,
    };
}
