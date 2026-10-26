import { existsSync,readFileSync,readdirSync } from 'node:fs';
import path from 'node:path';
import { expect,it } from 'vitest';
const root=new URL('../',import.meta.url);
function files(folder:string):string[]{return readdirSync(new URL(folder,root),{withFileTypes:true}).flatMap(entry=>entry.isDirectory()?files(folder+'/'+entry.name):/\.[cm]?tsx?$/.test(entry.name)?[folder+'/'+entry.name]:[]);}
it('keeps shared preview and citation packages free of host imports or host stores',()=>{
 for(const file of [...files('packages/file-viewers/src'),...files('packages/chat/src/citations')]){
  const source=readFileSync(new URL(file,root),'utf8');
  expect(source,file).not.toMatch(/from\s+['"](?:~\/|@\/|.*(?:client|platform)\/src\/|recoil['"]|zustand['"])/);
 }
});
it('exposes a pure citation entry without pulling renderers into export consumers',()=>{
 const entry=readFileSync(new URL('packages/chat/src/citations/index.ts',root),'utf8');
 expect(entry).not.toMatch(/citation-views|CitationDocumentPreview|CitationReferences|\.tsx|pdfjs-dist|mammoth/);
});
it('removes the unreachable old client preview graph instead of keeping a second renderer',()=>{
 for(const name of ['components/PreviewFile/FileView.tsx','components/PreviewFile/DocxFileViewer.tsx','components/PreviewFile/TxtFileViewer.tsx','components/PreviewFile/index.tsx','pages/appChat/components/ResouceModal.tsx'])expect(existsSync(new URL('client/src/'+name,root)),name).toBe(false);
});
it('keeps new shared presentation source files within the maintained component size boundary',()=>{
 for(const file of [...files('packages/chat/src/citations'),...files('packages/file-viewers/src/pdf')]){
  expect(readFileSync(new URL(file,root),'utf8').trimEnd().split('\n').length,path.basename(file)).toBeLessThanOrEqual(600);
 }
});
