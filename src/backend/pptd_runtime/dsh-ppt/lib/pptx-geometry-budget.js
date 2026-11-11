import { SaxesParser } from 'saxes';

export const MAX_NATIVE_GEOMETRY_CHARACTERS=262144;
export const GEOMETRY_BUDGET_NAMESPACE='urn:dsh:pptx:geometry-budget';
const DRAWINGML='http://schemas.openxmlformats.org/drawingml/2006/main';

/** Inspect vector complexity before allocating DOM trees. Oversized geometry
 * already uses a placeholder at conversion; retain its enclosing shape's frame,
 * text, transforms and layer order while omitting the expensive path tree.
 */
export function boundedPptxGeometry(xml) {
  if(!xml.includes('custGeom'))return xml;
  const parser=new SaxesParser({xmlns:true}),spans=[];
  let active;
  parser.on('opentag',tag=>{
    if(tag.local==='custGeom'&&tag.uri===DRAWINGML) {
      if(active)throw new Error('PPTX 图形几何结构无效');
      active={start:xml.lastIndexOf('<',parser.position-1),prefix:tag.prefix};
    }
  });
  parser.on('closetag',tag=>{
    if(tag.local==='custGeom'&&tag.uri===DRAWINGML&&active) {
      if(parser.position-active.start>MAX_NATIVE_GEOMETRY_CHARACTERS)spans.push({...active,end:parser.position});
      active=undefined;
    }
  });
  parser.on('error',()=>{throw new Error('PPTX 图形 XML 无效');});
  parser.write(xml).close();
  if(!spans.length)return xml;
  let offset=0;const output=[];
  for(const span of spans) {
    const prefix=span.prefix?span.prefix+':':'';
    const namespace=span.prefix?`xmlns:${span.prefix}`:'xmlns';
    output.push(xml.slice(offset,span.start),`<${prefix}prstGeom ${namespace}="${DRAWINGML}" xmlns:dshBudget="${GEOMETRY_BUDGET_NAMESPACE}" dshBudget:placeholder="geometry" prst="rect"><${prefix}avLst/></${prefix}prstGeom>`);
    offset=span.end;
  }
  output.push(xml.slice(offset));return output.join('');
}
