import { JSDOM } from 'jsdom';
import { SaxesParser } from 'saxes';
import { MAX_NATIVE_GEOMETRY_CHARACTERS } from './pptx-geometry-budget.js';
import { createHash } from 'node:crypto';
import { DRAWINGML_PRESET_SHAPES } from './drawingml-shapes.js';
const A='http://schemas.openxmlformats.org/drawingml/2006/main';
const geometryTags=new Set('prstGeom custGeom avLst gd gdLst ahLst ahXY ahPolar pos cxnLst cxn rect pathLst path moveTo lnTo arcTo quadBezTo cubicBezTo close pt'.split(' '));
const fillTags=new Set('solidFill noFill gradFill pattFill gsLst gs lin path fillToRect tileRect fgClr bgClr srgbClr scrgbClr hslClr sysClr prstClr alpha alphaMod alphaOff lum lumMod lumOff tint shade sat satMod satOff hue hueMod hueOff comp inv gray gamma invGamma red redMod redOff green greenMod greenOff blue blueMod blueOff'.split(' '));
const lineTags=new Set([...fillTags,...'ln prstDash custDash ds round bevel miter headEnd tailEnd'.split(' ')]);
// Bound retained XML trees by source size as well as entry count.
const cache=new Map();
const MAX_CACHED_XML_CHARACTERS=512*1024;
let cachedCharacters=0;
const validations=new Map();
let validatedCharacters=0;
let parserWindow;
function inspectPart(xml,kind='geometry') {
  if(typeof xml!=='string'||xml.length>MAX_NATIVE_GEOMETRY_CHARACTERS||/<!DOCTYPE|<!ENTITY/i.test(xml))throw new Error('图形几何应为有界、独立的 DrawingML');
  const parser=new SaxesParser({xmlns:true});let root,pathCount=0;
  parser.on('opentag',node=>{
    const allowed=kind==='ends'?['headEnd','tailEnd'].includes(node.local):kind==='fill'?fillTags.has(node.local):kind==='line'?lineTags.has(node.local):geometryTags.has(node.local);
    if(node.uri!==A||!allowed)throw new Error('图形数据应包含独立的 DrawingML 指令');
    for(const attr of Object.values(node.attributes))if(attr.uri&&attr.uri!=='http://www.w3.org/2000/xmlns/')throw new Error('图形几何应包含独立的局部属性');
    root??={name:node.local,preset:node.attributes.prst?.value};
    if(node.local==='path')pathCount++;
  });
  parser.on('error',()=>{throw new Error('图形几何 XML 无效');});
  parser.write(xml).close();
  if(!root)throw new Error('图形几何 XML 无效');
  return {...root,pathCount};
}
function validateNativeShape(element) {
  const value=element.nativeShape;
  if(!value||typeof value!=='object'||Array.isArray(value)||Object.keys(value).some(key=>!['geometry','lineEnds','fill','line','modelDigest','paintDigest','lineDigest'].includes(key)))throw new Error('原生图形数据无效');
  for(const field of ['modelDigest','paintDigest','lineDigest'])if(value[field]!==undefined&&!/^[a-f0-9]{64}$/.test(value[field]))throw new Error('原生图形绑定摘要无效');
  const key=JSON.stringify(value);if(validations.has(key))return validations.get(key);
  const geometry=inspectPart(value.geometry);
  if(geometry.name==='prstGeom') {
    if(!DRAWINGML_PRESET_SHAPES.has(geometry.preset))throw new Error('预设图形应属于 DrawingML 标准');
  } else if(geometry.name!=='custGeom'||!geometry.pathCount)throw new Error('自定义图形应包含原生路径');
  if(value.lineEnds!==undefined&&(!Array.isArray(value.lineEnds)||value.lineEnds.length>2))throw new Error('连接符端点数据无效');
  const ends=(value.lineEnds??[]).map(xml=>inspectPart(xml,'ends').name);
  if(new Set(ends).size!==ends.length)throw new Error('连接符端点类型重复');
  if(value.fill!==undefined&&!['solidFill','noFill','gradFill','pattFill'].includes(inspectPart(value.fill,'fill').name))throw new Error('图形填充数据无效');
  if(value.line!==undefined&&inspectPart(value.line,'line').name!=='ln')throw new Error('图形轮廓数据无效');
  while(validations.size&&(validations.size>=64||validatedCharacters+key.length>MAX_CACHED_XML_CHARACTERS)) {
    const oldest=validations.keys().next().value;validatedCharacters-=oldest.length;validations.delete(oldest);
  }
  if(key.length<=MAX_CACHED_XML_CHARACTERS){validations.set(key,geometry);validatedCharacters+=key.length;}
  return geometry;
}
function parsePart(xml,kind='geometry') {
  if(typeof xml!=='string'||xml.length>MAX_NATIVE_GEOMETRY_CHARACTERS||/<!DOCTYPE|<!ENTITY/i.test(xml)) throw new Error('图形几何应为有界、独立的 DrawingML');
  parserWindow??=new JSDOM('').window;
  const doc=new parserWindow.DOMParser().parseFromString(xml,'application/xml');
  const root=doc.documentElement;
  if(doc.getElementsByTagName('parsererror').length||root.namespaceURI!==A)throw new Error('图形几何 XML 无效');
  for(const node of [root,...root.getElementsByTagName('*')]) {
    const allowed=kind==='ends'?['headEnd','tailEnd'].includes(node.localName):kind==='fill'?fillTags.has(node.localName):kind==='line'?lineTags.has(node.localName):geometryTags.has(node.localName);
    if(node.namespaceURI!==A||!allowed)throw new Error('图形数据应包含独立的 DrawingML 指令');
    for(const attr of node.attributes)if(attr.namespaceURI&&attr.namespaceURI!=='http://www.w3.org/2000/xmlns/')throw new Error('图形几何应包含独立的局部属性');
  }
  return root;
}
function nativeParts(element) {
  validateNativeShape(element);
  const value=element.nativeShape;
  if(!value||typeof value!=='object'||Array.isArray(value)||Object.keys(value).some(key=>!['geometry','lineEnds','fill','line','modelDigest','paintDigest','lineDigest'].includes(key)))throw new Error('原生图形数据无效');
  for(const field of ['modelDigest','paintDigest','lineDigest'])if(value[field]!==undefined&&!/^[a-f0-9]{64}$/.test(value[field]))throw new Error('原生图形绑定摘要无效');
  const key=JSON.stringify(value);
  let parts=cache.get(key);
  if(!parts) {
    while(cache.size && (cache.size>=64 || cachedCharacters+key.length>MAX_CACHED_XML_CHARACTERS)) {
      const oldest=cache.keys().next().value;cachedCharacters-=oldest.length;cache.delete(oldest);
    }
    const geometry=parsePart(value.geometry);
    if(geometry.localName==='prstGeom') {
      if(!DRAWINGML_PRESET_SHAPES.has(geometry.getAttribute('prst')))throw new Error('预设图形应属于 DrawingML 标准');
    } else if(geometry.localName!=='custGeom'||!geometry.getElementsByTagNameNS(A,'path').length)throw new Error('自定义图形应包含原生路径');
    if(value.lineEnds!==undefined&&(!Array.isArray(value.lineEnds)||value.lineEnds.length>2))throw new Error('连接符端点数据无效');
    const lineEnds=(value.lineEnds??[]).map(xml=>parsePart(xml,'ends'));
    if(new Set(lineEnds.map(node=>node.localName)).size!==lineEnds.length)throw new Error('连接符端点类型重复');
    const fill=value.fill===undefined?undefined:parsePart(value.fill,'fill');
    if(fill&&!['solidFill','noFill','gradFill','pattFill'].includes(fill.localName))throw new Error('图形填充数据无效');
    const line=value.line===undefined?undefined:parsePart(value.line,'line');
    if(line&&line.localName!=='ln')throw new Error('图形轮廓数据无效');
    parts={geometry,lineEnds,fill,line};
    if(key.length<=MAX_CACHED_XML_CHARACTERS) {cache.set(key,parts);cachedCharacters+=key.length;}
  }
  return parts;
}
export function nativeShapeIssue(element) {
  if(element.nativeShape===undefined)return undefined;
  try {validateNativeShape(element);}catch(error){return error.message;}
}
const modelDigest=element=>createHash('sha256').update(JSON.stringify([element.shapeName,element.path??null,element.viewBox??null,element.adjustments??null])).digest('hex');
const paintDigest=element=>createHash('sha256').update(JSON.stringify([element.fill??null,element.opacity??null])).digest('hex');
const lineDigest=element=>createHash('sha256').update(JSON.stringify([element.border??null,element.opacity??null])).digest('hex');
export function markNativeShape(element) {
  return element.nativeShape ? {...element,nativeShape:{...element.nativeShape,modelDigest:modelDigest(element),paintDigest:paintDigest(element),lineDigest:lineDigest(element)}} : element;
}
export function hasNativeShape(element) {
  if(element.nativeShape===undefined||element.nativeShape.modelDigest!==modelDigest(element)||nativeShapeIssue(element)!==undefined)return false;
  const geometry=validateNativeShape(element);
  return geometry.name==='prstGeom'?geometry.preset===element.shapeName:element.shapeName==='custom';
}
/** Restore editable source geometry and unchanged paint in the generated slide. */
export function restoreImportedShapes(doc,shapes,elements) {
      for(const element of elements.filter(hasNativeShape)) {
        const shape=shapes.get(element.elementId),spPr=shape&&[...shape.children].find(node=>node.localName==='spPr');
        if(!spPr)throw new Error(`Missing editable imported shape: ${element.elementId}`);
        const native=nativeParts(element);
        const existing=[...spPr.children].find(node=>['prstGeom','custGeom'].includes(node.localName));
        if(!existing)throw new Error('Missing generated shape geometry');
        existing.replaceWith(doc.importNode(native.geometry,true));
        if(native.fill&&element.nativeShape.paintDigest===paintDigest(element)) {
          [...spPr.children].filter(node=>['solidFill','noFill','gradFill','pattFill','blipFill','grpFill'].includes(node.localName)).forEach(node=>node.remove());
          const imported=doc.importNode(native.fill,true);
          const next=[...spPr.children].find(node=>['ln','effectLst','effectDag','scene3d','sp3d','extLst'].includes(node.localName));
          spPr.insertBefore(imported,next??null);
        }
        if(native.line&&element.nativeShape.lineDigest===lineDigest(element)) {
          const existingLine=[...spPr.children].find(node=>node.localName==='ln');
          const imported=doc.importNode(native.line,true);
          if(existingLine)existingLine.replaceWith(imported);
          else spPr.insertBefore(imported,[...spPr.children].find(node=>['effectLst','effectDag','scene3d','sp3d','extLst'].includes(node.localName))??null);
        }
        if(native.lineEnds.length) {
          let line=[...spPr.children].find(node=>node.localName==='ln');
          if(!line){line=doc.createElementNS(A,'a:ln');spPr.append(line);}
          for(const end of native.lineEnds) {
            [...line.children].filter(node=>node.localName===end.localName).forEach(node=>node.remove());
            line.append(doc.importNode(end,true));
          }
        }
      }
}
