import { TextDecoder, TextEncoder } from "util";

// jsdom omits these; jszip needs them to read the zip's string entries.
(global as any).TextDecoder = (global as any).TextDecoder ?? TextDecoder;
(global as any).TextEncoder = (global as any).TextEncoder ?? TextEncoder;

import JSZip from "jszip";

import { sanitizeDocxForPreview } from "./docxSanitizer";

const SEAL_PAYLOAD = "ZUMoY14gcGUxYRAla2Hfc18xYBAgalPfc2AyOC83aVvfclUxb1kuaizhLR3vHhAkalMuYFkt";

/**
 * Mirrors how a Chinese e-seal really ships: the payload sits in a zero-sized text box
 * inside mc:Choice, with an mc:Fallback carrying the same payload as legacy VML.
 */
function buildDocumentXml(): string {
    return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document
  xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
  xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006"
  xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
  xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
  xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape"
  xmlns:v="urn:schemas-microsoft-com:vml">
  <w:body>
    <w:p><w:r><w:t>各单位：</w:t></w:r></w:p>
    <w:p>
      <w:r>
        <mc:AlternateContent>
          <mc:Choice Requires="wps">
            <w:drawing>
              <wp:anchor>
                <wp:extent cx="0" cy="0"/>
                <a:graphic>
                  <a:graphicData uri="http://schemas.microsoft.com/office/word/2010/wordprocessingShape">
                    <wps:wsp>
                      <wps:spPr><a:xfrm><a:off x="4621530" y="8742045"/><a:ext cx="0" cy="0"/></a:xfrm></wps:spPr>
                      <wps:txbx>
                        <w:txbxContent>
                          <w:p><w:r><w:rPr><w:sz w:val="10"/></w:rPr><w:t>${SEAL_PAYLOAD}</w:t></w:r></w:p>
                        </w:txbxContent>
                      </wps:txbx>
                    </wps:wsp>
                  </a:graphicData>
                </a:graphic>
              </wp:anchor>
            </w:drawing>
          </mc:Choice>
          <mc:Fallback>
            <w:pict>
              <v:shape><v:textbox><w:txbxContent>
                <w:p><w:r><w:rPr><w:sz w:val="10"/></w:rPr><w:t>${SEAL_PAYLOAD}</w:t></w:r></w:p>
              </w:txbxContent></v:textbox></v:shape>
            </w:pict>
          </mc:Fallback>
        </mc:AlternateContent>
      </w:r>
    </w:p>
    <w:p><w:r><w:t>北京首钢股份有限公司</w:t></w:r></w:p>
  </w:body>
</w:document>`;
}

async function buildDocx(documentXml: string): Promise<ArrayBuffer> {
    const zip = new JSZip();
    zip.file(
        "[Content_Types].xml",
        `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="xml" ContentType="application/xml"/>
</Types>`,
    );
    zip.file("word/document.xml", documentXml);
    const generated = await zip.generateAsync({ type: "arraybuffer" });
    // Rebuild in the jsdom realm so JSZip's `instanceof ArrayBuffer` check passes;
    // in the browser this is a genuine ArrayBuffer from response.arrayBuffer().
    const copy = new ArrayBuffer(generated.byteLength);
    new Uint8Array(copy).set(new Uint8Array(generated));
    return copy;
}

async function readDocumentXml(arrayBuffer: ArrayBuffer): Promise<string> {
    const zip = await JSZip.loadAsync(arrayBuffer);
    return zip.files["word/document.xml"].async("string");
}

describe("sanitizeDocxForPreview", () => {
    it("drops the e-seal payload together with its Fallback copy", async () => {
        const result = await sanitizeDocxForPreview(await buildDocx(buildDocumentXml()));
        const xml = await readDocumentXml(result.arrayBuffer);

        expect(result.removedZeroSizedDrawings).toBe(1);
        // Both copies must go: leaving the Fallback would let mammoth render the
        // payload again once the Choice is emptied.
        expect(xml).not.toContain(SEAL_PAYLOAD);
        expect(xml).not.toContain("AlternateContent");
        // Real body text is untouched.
        expect(xml).toContain("各单位：");
        expect(xml).toContain("北京首钢股份有限公司");
    });

    it("keeps drawings that have a real size", async () => {
        const xml = buildDocumentXml()
            .replace('<wp:extent cx="0" cy="0"/>', '<wp:extent cx="1557020" cy="1617345"/>')
            .replace('<a:ext cx="0" cy="0"/>', '<a:ext cx="1557020" cy="1617345"/>');
        const result = await sanitizeDocxForPreview(await buildDocx(xml));

        expect(result.removedZeroSizedDrawings).toBe(0);
        // A visible shape's text is real content and must survive.
        expect(await readDocumentXml(result.arrayBuffer)).toContain(SEAL_PAYLOAD);
    });

    it("leaves a document without drawings byte-for-byte intact", async () => {
        const xml = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body><w:p><w:r><w:t>普通文档</w:t></w:r></w:p></w:body>
</w:document>`;
        const result = await sanitizeDocxForPreview(await buildDocx(xml));

        expect(result.removedZeroSizedDrawings).toBe(0);
        expect(await readDocumentXml(result.arrayBuffer)).toBe(xml);
    });
});
