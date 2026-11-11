import { hasSourceLayout } from './source-layout.js';
import { resolveFontFace } from './font-family.js';
const escape = value => String(value).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
const emu = value => Math.round((Number(value) || 0)*12700);
const color = value => /^[0-9a-f]{6}$/i.test(String(value).replace(/^#/,'')) ? String(value).replace(/^#/,'') : '000000';
function textBody(content) {
  const [top,right,bottom,left]=content.margins ?? [0,0,0,0];
  const fit=content.overflow==='visible'?'<a:spAutoFit/>':content.fit==='shrink'?`<a:normAutofit${content.fontScale?` fontScale="${Math.round(content.fontScale*100000)}"`:''}/>`:'<a:noAutofit/>';
  const paragraphs=content.paragraphs.map(paragraph=>{
    const align=({center:'ctr',right:'r',justify:'just'})[paragraph.align] ?? 'l';
    const line=paragraph.lineSpacing?`<a:spcPts val="${Math.round(paragraph.lineSpacing*100)}"/>`:`<a:spcPct val="${Math.round((paragraph.lineHeight??1)*100000)}"/>`;
    const tabs=(paragraph.tabStops??[]).map(tab=>`<a:tab pos="${emu(tab.position)}" algn="${['l','r','ctr','dec'].includes(tab.alignment)?tab.alignment:'l'}"/>`).join('');
    const numbering=paragraph.numbering?`<a:buAutoNum type="${escape(paragraph.numbering.type)}" startAt="${paragraph.numbering.startAt??1}"/>`:'<a:buNone/>';
    const props=`<a:pPr marL="${emu(paragraph.marginLeft)}" marR="${emu(paragraph.marginRight)}" indent="${emu(paragraph.indent)}" algn="${align}"><a:lnSpc>${line}</a:lnSpc><a:spcBef><a:spcPts val="${Math.round((paragraph.spaceBefore??0)*100)}"/></a:spcBef><a:spcAft><a:spcPts val="${Math.round((paragraph.spaceAfter??0)*100)}"/></a:spcAft>${numbering}${tabs?`<a:tabLst>${tabs}</a:tabLst>`:''}</a:pPr>`;
    const runs=paragraph.runs.map(run=>{
      const o={...content,...run.options}, size=o.fontSize??18;
      const family=resolveFontFace(o.fontFamily,'Arial',run.text);
      return `<a:r><a:rPr sz="${Math.round(size*100)}" b="${o.bold?'1':'0'}" i="${o.italic?'1':'0'}" spc="${Math.round((o.letterSpacing??0)*100)}" baseline="${Math.round((o.baseline??0)/size*100000)}"${o.underline?' u="sng"':''}><a:solidFill><a:srgbClr val="${color(o.color)}"/></a:solidFill>${o.highlight?`<a:highlight><a:srgbClr val="${color(o.highlight)}"/></a:highlight>`:''}<a:latin typeface="${escape(family)}"/><a:ea typeface="${escape(family)}"/><a:cs typeface="${escape(family)}"/></a:rPr><a:t xml:space="preserve">${escape(run.text)}</a:t></a:r>`;
    }).join('');
    return `<a:p>${props}${runs}<a:endParaRPr sz="${Math.round((paragraph.fontSize??content.fontSize??18)*100)}"/></a:p>`;
  }).join('');
  const anchor=content.align?.[1]==='middle'?'ctr':content.align?.[1]==='bottom'?'b':'t';
  return `<p:txBody xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><a:bodyPr wrap="${content.wrap===false?'none':'square'}" lIns="${emu(left)}" tIns="${emu(top)}" rIns="${emu(right)}" bIns="${emu(bottom)}" anchor="${anchor}">${fit}</a:bodyPr><a:lstStyle/>${paragraphs}</p:txBody>`;
}
/** One editable object per source textbox keeps semantic bindings stable. The generated
 * DrawingML carries every preserved paragraph property without relying on HTML flattening.
 */
export function restoreImportedText(doc, shapes, elements, parser) {
      for(const element of elements) {
        if(!hasSourceLayout(element)||!Array.isArray(element.content?.paragraphs))continue;
        const shape=shapes.get(element.elementId);
        if(!shape)throw new Error(`Missing editable imported textbox: ${element.elementId}`);
        const nonVisual=shape.getElementsByTagNameNS('*','cNvSpPr')[0];
        if(nonVisual)nonVisual.setAttribute('txBox',element.content.textBox?'1':'0');
        const source=element.content.nativeTextBody ?? textBody(element.content);
        if(/<!DOCTYPE|<!ENTITY/i.test(source))throw new Error('Imported text requires self-contained DrawingML');
        const body=parser.parseFromString(source,'application/xml');
        if(body.documentElement.namespaceURI!=='http://schemas.openxmlformats.org/presentationml/2006/main'||body.documentElement.localName!=='txBody'||body.getElementsByTagName('parsererror').length)throw new Error('Imported paragraph serialization failed');
        for(const n of [body.documentElement,...body.getElementsByTagName('*')]) {
          for(const attribute of [...n.attributes]) if(attribute.namespaceURI==='http://schemas.openxmlformats.org/officeDocument/2006/relationships') n.removeAttributeNode(attribute);
        }
        const original=[...shape.children].find(n=>n.localName==='txBody');
        if(original)original.replaceWith(doc.importNode(body.documentElement,true));
        else shape.appendChild(doc.importNode(body.documentElement,true));
      }
}
