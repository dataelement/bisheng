import { createHash } from 'node:crypto';
import path from 'node:path';
import { JSDOM } from 'jsdom';
import { strFromU8, strToU8 } from 'fflate';
import { hasSourceLayout } from './source-layout.js';
import { hasNativeShape, restoreImportedShapes } from './imported-shape-export.js';
import { restoreImportedText } from './imported-text-export.js';
import { restoreImageCrops } from './image-crop.js';

/** Generated slides share one media part for identical resources. */
export async function deduplicatePptxMedia(entries) {
  const originals=new Map(), replacements=new Map();
  for(const [name,bytes] of Object.entries(entries)) {
    if(!name.startsWith('ppt/media/')||name.endsWith('/'))continue;
    const key=path.posix.extname(name).toLowerCase()+':'+createHash('sha256').update(bytes).digest('hex');
    if(originals.has(key))replacements.set(name,originals.get(key));
    else originals.set(key,name);
  }
  if(!replacements.size)return false;
  const window=new JSDOM('').window,parser=new window.DOMParser();
  try {
    for(const [name,bytes] of Object.entries(entries)) {
      if(!name.endsWith('.rels'))continue;
      await new Promise(resolve=>setImmediate(resolve));
      const source=name.replace(/(^|\/)_rels\//,'$1').replace(/\.rels$/,'');
      const directory=path.posix.dirname(source),doc=parser.parseFromString(strFromU8(bytes),'application/xml');
      let changed=false;
      for(const relation of doc.getElementsByTagNameNS('*','Relationship')) {
        if(relation.getAttribute('TargetMode')==='External')continue;
        const target=relation.getAttribute('Target')??'';
        const absolute=target.startsWith('/')?target.slice(1):path.posix.normalize(path.posix.join(directory,target));
        const replacement=replacements.get(absolute);
        if(!replacement)continue;
        relation.setAttribute('Target',path.posix.relative(directory,replacement));changed=true;
      }
      if(changed)entries[name]=strToU8(new window.XMLSerializer().serializeToString(doc));
    }
    for(const duplicate of replacements.keys())delete entries[duplicate];
  } finally {window.close();}
  return true;
}

/** Restore text and shapes together: one slide parse and one final ZIP compression. */
export async function restoreImportedSlides(entries,pages) {
  const pending=pages.map((page,index)=>({page,index})).filter(({page})=>page.elements.some(element=>hasNativeShape(element)||(element.elementType==='image'&&element.crop!==undefined)||(hasSourceLayout(element)&&Array.isArray(element.content?.paragraphs))));
  if(!pending.length)return false;
  const window=new JSDOM('').window,parser=new window.DOMParser();
  try {
    for(const {page,index} of pending) {
      await new Promise(resolve=>setImmediate(resolve));
      const key=`ppt/slides/slide${index+1}.xml`,doc=parser.parseFromString(strFromU8(entries[key]),'application/xml');
      if(doc.getElementsByTagName('parsererror').length)throw new Error('Generated slide XML is invalid');
      const shapes=new Map([...doc.getElementsByTagNameNS('*','sp')].map(shape=>[shape.getElementsByTagNameNS('*','cNvPr')[0]?.getAttribute('name'),shape]));
      restoreImportedText(doc,shapes,page.elements,parser);
      restoreImportedShapes(doc,shapes,page.elements);
      restoreImageCrops(doc,page.elements);
      entries[key]=strToU8(new window.XMLSerializer().serializeToString(doc));
    }
  } finally {window.close();}
  return true;
}
