const A='http://schemas.openxmlformats.org/drawingml/2006/main';
const fills=new Set(['noFill','solidFill','gradFill','pattFill','blipFill','grpFill']);
const colors=new Set(['srgbClr','schemeClr','sysClr','prstClr','scrgbClr','hslClr']);
const child=(node,name)=>[...(node?.children??[])].find(item=>item.localName===name);
const paint=node=>[...(node?.children??[])].find(item=>fills.has(item.localName));
const element=value=>value?.element;

function referencedStyle(style,reference) {
 if(!style)return undefined;
 const copy=style.cloneNode(true),color=[...(reference?.children??[])].find(item=>colors.has(item.localName));
 if(color)for(const placeholder of [...copy.getElementsByTagNameNS(A,'schemeClr')].filter(item=>item.getAttribute('val')==='phClr')) {
  const replacement=copy.ownerDocument.importNode(color,true);
  for(const transform of placeholder.children)replacement.append(copy.ownerDocument.importNode(transform,true));
  placeholder.replaceWith(replacement);
 }
 return copy;
}
const lineGroup=name=>fills.has(name)?'fill':['prstDash','custDash'].includes(name)?'dash':['round','bevel','miter'].includes(name)?'join':name;

/** Background references use the same local theme fill matrix as shape styles. */
export function resolvePptxBackgroundStyle(source,theme) {
 const reference=child(source,'bgRef'),index=Number(reference?.getAttribute('idx')??0);
 const style=index>=1001?theme?.bgFillStyles?.[index-1001]:theme?.fillStyles?.[index-1];
 const fill=paint(child(source,'bgPr'))??referencedStyle(element(style),reference);
 return fill?{element:fill}:undefined;
}

/** Resolve the theme style matrix, then apply the shape's local paint overrides.
 * A partial source line can supply an arrowhead while its color and width come
 * from lnRef; all resolved XML stays local to the imported shape.
 */
export function resolvePptxShapeStyle(source,theme) {
 const properties=child(source,'spPr'),style=child(source,'style');
 const fillReference=child(style,'fillRef'),fillIndex=Number(fillReference?.getAttribute('idx')??0);
 const fillStyle=fillIndex>=1001?theme?.bgFillStyles?.[fillIndex-1001]:theme?.fillStyles?.[fillIndex-1];
 const fill=paint(properties)??referencedStyle(element(fillStyle),fillReference);
 const lineReference=child(style,'lnRef'),lineIndex=Number(lineReference?.getAttribute('idx')??0);
 const localLine=child(properties,'ln'),baseLine=referencedStyle(element(theme?.lineStyles?.[lineIndex-1]),lineReference);
 let line=localLine;
 if(baseLine) {
  line=baseLine;
  if(localLine) {
   for(const attr of localLine.attributes)if(attr.namespaceURI===null)line.setAttribute(attr.name,attr.value);
   for(const local of localLine.children) {
    [...line.children].filter(item=>lineGroup(item.localName)===lineGroup(local.localName)).forEach(item=>item.remove());
    line.append(line.ownerDocument.importNode(local,true));
   }
  }
  const order=['noFill','solidFill','gradFill','pattFill','blipFill','grpFill','prstDash','custDash','round','bevel','miter','headEnd','tailEnd','extLst'];
  [...line.children].sort((a,b)=>order.indexOf(a.localName)-order.indexOf(b.localName)).forEach(item=>line.append(item));
 }
 return {fill:fill?{element:fill}:undefined,line:line?{element:line}:undefined};
}
