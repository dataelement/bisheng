import { sanitizeOoXml, serializeOoXmlElement } from './pptx-resources.js';

const child=(n,name)=>[...n.children].find(c=>c.localName===name);
const value=(n,a,f=0)=>Number(n?.getAttribute(a)??f);
const multiply=(m,n)=>[m[0]*n[0]+m[2]*n[1],m[1]*n[0]+m[3]*n[1],m[0]*n[2]+m[2]*n[3],m[1]*n[2]+m[3]*n[3],m[0]*n[4]+m[2]*n[5]+m[4],m[1]*n[4]+m[3]*n[5]+m[5]];
const identity=[1,0,0,1,0,0];
const transform=(node,group=false)=>{
 const off=child(node,'off'),ext=child(node,'ext'),co=child(node,'chOff'),ce=child(node,'chExt');
 const x=value(off,'x'),y=value(off,'y'),w=value(ext,'cx'),h=value(ext,'cy');
 const sx=group?w/value(ce,'cx',w||1):1,sy=group?h/value(ce,'cy',h||1):1;
 const angle=value(node,'rot')/60000*Math.PI/180,c=Math.cos(angle),s=Math.sin(angle),fx=['1','true'].includes(node.getAttribute('flipH'))?-1:1,fy=['1','true'].includes(node.getAttribute('flipV'))?-1:1;
 const centered=[c*fx,s*fx,-s*fy,c*fy,x+w/2,y+h/2];
 const base=group?[sx,0,0,sy,-value(co,'x')*sx-w/2,-value(co,'y')*sy-h/2]:[1,0,0,1,-w/2,-h/2];
 return {matrix:multiply(centered,base),w,h};
};
/** Flatten group coordinates in OOXML before model extraction, retaining each child's styles.
 * The affine transform composes child offsets, scaling, rotation and reflection through nesting.
 */
export function flattenPptxGroups(xml) {
 const source=sanitizeOoXml(xml);
 if(!/<(?:[A-Za-z_][\w.-]*:)?grpSp(?:\s|>)/u.test(source))return {xml:source,count:0};
 const doc=new DOMParser().parseFromString(source,'application/xml');
 if(doc.querySelector('parsererror'))return{xml:source,count:0};
 const tree=[...doc.getElementsByTagNameNS('*','spTree')][0];if(!tree)return{xml:source,count:0};
 let count=0;const fallbacks=[];
 function walk(parent,matrix,depth,groupFill){
  if(depth>64)throw new Error('PPTX 组合层级超过解析限制');
  for(const node of[...parent.children]){
   if(node.localName==='grpSp'){
    const props=child(node,'grpSpPr'),xf=props&&child(props,'xfrm');
    if(!xf)throw new Error('PPTX 组合坐标缺失');
    const fill=[...props.children].find(n=>['solidFill','gradFill','blipFill','noFill'].includes(n.localName))??groupFill;
    const t=transform(xf,true);if(t.matrix.some(n=>!Number.isFinite(n)))throw new Error('PPTX 组合尺寸无效');
    walk(node,multiply(matrix,t.matrix),depth+1,fill);count++;
    for(const item of[...node.children])if(!['nvGrpSpPr','grpSpPr'].includes(item.localName))parent.insertBefore(item,node);
    node.remove();
   }else if(depth>0&&['sp','pic','cxnSp','graphicFrame'].includes(node.localName)){
    const props=child(node,'spPr'),xf=props?child(props,'xfrm'):child(node,'xfrm');
    if(!xf)throw new Error('PPTX 组合内对象坐标缺失');
    if(groupFill&&props){const inherited=child(props,'grpFill');if(inherited)inherited.replaceWith(groupFill.cloneNode(true));}
    const t=transform(xf),m=multiply(matrix,t.matrix),sx=Math.hypot(m[0],m[1]),sy=Math.hypot(m[2],m[3]);
    if(m.some(n=>!Number.isFinite(n)))throw new Error('PPTX 组合内对象尺寸无效');
    if(!sx||!sy||Math.abs(m[0]*m[2]+m[1]*m[3])>sx*sy*1e-6){
     // PPTD frames represent rotation and reflection. A general affine map needs
     // a placeholder at the exact transformed envelope, keeping painter order.
     const corners=[[0,0],[t.w,0],[0,t.h],[t.w,t.h]].map(([x,y])=>[m[0]*x+m[2]*y+m[4],m[1]*x+m[3]*y+m[5]]);
     const left=Math.min(...corners.map(p=>p[0])),top=Math.min(...corners.map(p=>p[1]));
     const right=Math.max(...corners.map(p=>p[0])),bottom=Math.max(...corners.map(p=>p[1]));
     const off=child(xf,'off'),ext=child(xf,'ext');
     off.setAttribute('x',String(Math.round(left)));off.setAttribute('y',String(Math.round(top)));
     ext.setAttribute('cx',String(Math.round(right-left)));ext.setAttribute('cy',String(Math.round(bottom-top)));
     xf.removeAttribute('rot');xf.removeAttribute('flipH');xf.removeAttribute('flipV');
     fallbacks.push({nodeId:node.getElementsByTagNameNS('*','cNvPr')[0]?.getAttribute('id'),feature:'group-affine',message:'组合的非正交变换使用原位置和变换后外接框占位。'});
     continue;
    }
    const width=t.w*sx,height=t.h*sy,cx=m[0]*t.w/2+m[2]*t.h/2+m[4],cy=m[1]*t.w/2+m[3]*t.h/2+m[5];
    const off=child(xf,'off'),ext=child(xf,'ext');off.setAttribute('x',String(Math.round(cx-width/2)));off.setAttribute('y',String(Math.round(cy-height/2)));ext.setAttribute('cx',String(Math.round(width)));ext.setAttribute('cy',String(Math.round(height)));
    xf.removeAttribute('flipH');xf.removeAttribute('flipV');if(m[0]*m[3]-m[1]*m[2]<0)xf.setAttribute('flipV','1');
    const angle=(Math.atan2(m[1],m[0])*180/Math.PI+360)%360;xf.setAttribute('rot',String(Math.round(angle*60000)));
    // Group child coordinates can use an arbitrary local unit system. Text sizes
    // remain hundredths of a point and stroke widths remain EMUs in that system.
    // The affine map applies to geometry; keep these absolute style dimensions.
   }
  }
 }
 walk(tree,identity,0);
 if(!count)return{xml:source,count:0};
 return{xml:serializeOoXmlElement(doc.documentElement),count,fallbacks};
}
