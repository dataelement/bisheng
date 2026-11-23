import { layoutRichText } from './rich-text-layout.js';
/** Imported paragraphs keep their own indentation, tab stops, spacing and run styles.
 * Coordinates are points shared by SVG previews and the editable PPTX exporter.
 */
export function importedTextLines(content, bounds) {
  const [x,y,w,h] = bounds;
  const [top,right,bottom,left] = content.margins ?? [0,0,0,0];
  let cursorY = y + top;
  const output = [];
  for (const [paragraphIndex,paragraph] of content.paragraphs.entries()) {
    const lineHeight = paragraph.lineHeight ?? 1;
    if (paragraphIndex) cursorY += paragraph.spaceBefore ?? 0;
    const start = x + left + (paragraph.marginLeft ?? 0);
    const available = Math.max(.01, w-left-right-(paragraph.marginLeft ?? 0)-(paragraph.marginRight ?? 0));
    const groups = [[]];
    for (const run of paragraph.runs) {
      const chunks = run.text.split('\t');
      for (const [i,text] of chunks.entries()) {
        if (i) groups.push([]);
        if (text) groups.at(-1).push({text,options:{...run.options,lineHeight}});
      }
    }
    let pen = start + (paragraph.indent ?? 0), usedHeight = 0;
    const paragraphFontSize = Math.max(...paragraph.runs.map(run=>run.options?.fontSize ?? content.fontSize ?? 18), paragraph.fontSize ?? 0);
    for (const [index,runs] of groups.entries()) {
      if (index) {
        const next = paragraph.tabStops?.find(tab => x+left+tab.position > pen+.01);
        pen = next ? x+left+next.position : x+left+(Math.floor((pen-x-left)/36)+1)*36;
      }
      const layout = layoutRichText(runs, {...content,lineHeight,wrap:content.wrap,authored:true}, Math.max(.01,start+available-pen), 1e9);
      let offsetY = 0;
      for (const [lineIndex,line] of layout.lines.entries()) {
        const indentX = lineIndex && groups.length===1 ? start : pen;
        const align = paragraph.align ?? content.align?.[0];
        const lineX = groups.length>1 ? indentX : align==='center' ? start+(available-line.width)/2 : align==='right' ? start+available-line.width : indentX;
        const lineFontSize = groups.length>1 ? paragraphFontSize : line.fontSize;
        const height = paragraph.lineSpacing ?? Math.max(line.height,lineFontSize*lineHeight);
        output.push({...line,height,x:lineX,y:cursorY+offsetY,baseline:cursorY+offsetY+lineFontSize+(height-lineFontSize)/2,paragraph});
        offsetY += paragraph.lineSpacing ?? line.height;
      }
      usedHeight = Math.max(usedHeight, offsetY);
      pen += layout.lines.at(-1)?.width ?? 0;
    }
    if (!usedHeight) usedHeight = (paragraph.fontSize ?? content.fontSize ?? 18)*lineHeight;
    cursorY += usedHeight + (paragraphIndex < content.paragraphs.length-1 ? paragraph.spaceAfter ?? 0 : 0);
  }
  const required = cursorY-y-top;
  const vertical = content.align?.[1];
  const shift = vertical==='middle' ? (h-top-bottom-required)/2 : vertical==='bottom' ? h-top-bottom-required : 0;
  for (const line of output) {line.y+=shift;line.baseline+=shift;}
  return output;
}

/** Preserve a single native text object; its complete paragraphs are serialized after export. */
export function exportImportedText(slide, element, resolveFont) {
  const [x,y,w,h]=element.bounds;
  slide.addText(' ',{x:x/72,y:y/72,w:w/72,h:h/72,margin:0,objectName:element.elementId,
    fontFace:resolveFont(element.content.fontFamily,'Arial'),fontSize:element.content.fontSize??18,
    rotate:element.rotation??0,flipH:element.flip?.[0]??false,flipV:element.flip?.[1]??false});
}
