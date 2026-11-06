import React,{useEffect,useMemo,useRef,useState} from 'react';
import {createRoot} from 'react-dom/client';
import i18next from 'i18next';
import {I18nextProvider} from 'react-i18next';
import {usePreviewLocale} from '../packages/file-viewers/src/usePreviewLocale';
import {usePdfDocument,PdfViewer} from '../packages/file-viewers/src/pdf';
import {DocxViewer} from '../packages/file-viewers/src/viewers/DocxViewer';
import {TextViewer} from '../packages/file-viewers/src/viewers/TextViewer';
import {MarkdownViewer} from '../packages/file-viewers/src/viewers/MarkdownViewer';
import {HtmlViewer} from '../packages/file-viewers/src/viewers/HtmlViewer';
import {ImageViewer} from '../packages/file-viewers/src/viewers/ImageViewer';
import {MediaViewer} from '../packages/file-viewers/src/viewers/MediaViewer';
import {ExcelPreview} from '../packages/file-viewers/src/ExcelPreview';
import {loadDiagramLibrary} from '../packages/diagram-runtime/src';
import {CitationDocumentPreview} from '../packages/chat/src/citations/CitationDocumentPreview';
import en from '../packages/locales/src/shared/en.json';
import zh from '../packages/locales/src/shared/zh-Hans.json';
import ja from '../packages/locales/src/shared/ja.json';
__PLATFORM_IMPORT__
__HOST_CSS__
import '@bisheng/ui/tokens.css';
const base=__APP_ENV__.BASE_URL;
const url=(name:string)=>base+'/__f089__/fixtures/'+name;
const instance=i18next.createInstance();
const global=window as any;
global.__checks={errors:[],downloads:[],selections:[],sandbox:null};
window.addEventListener('message',event=>{if(event.data?.fixture==='sandbox')global.__checks.sandbox=event.data;});
function Diagrams(){
 const root=useRef<HTMLDivElement>(null);
 useEffect(()=>{let active=true;let dispose=()=>{};
  void(async()=>{const same=loadDiagramLibrary('echarts',{baseUrl:base});global.__checks.dedup=same===loadDiagramLibrary('echarts',{baseUrl:base});
   const echarts:any=await same;const mermaid:any=await loadDiagramLibrary('mermaid',{baseUrl:base});if(!active||!root.current)return;
   const chart=root.current.querySelector<HTMLElement>('[data-chart]')!;const drawing=echarts.init(chart);drawing.setOption({xAxis:{data:['A','B']},yAxis:{},series:[{type:'bar',data:[1,2]}]});dispose=()=>drawing.dispose();
   mermaid.initialize({startOnLoad:false});const result=await mermaid.render('fixture-mermaid','flowchart LR; A-->B');if(active)root.current.querySelector('[data-mermaid]')!.innerHTML=result.svg;
  })().catch(error=>global.__checks.errors.push(String(error)));
  return()=>{active=false;dispose();};
 },[]);
 return <div ref={root}><div data-chart style={{height:210,width:320}}/><div data-mermaid/></div>;
}
function App(){
 const locale=usePreviewLocale();const [mode,setMode]=useState('pdf');const [zoom,setZoom]=useState(100);const [scope,setScope]=useState('A');const [active,setActive]=useState(false);
 const pdf=usePdfDocument(mode==='pdf'?url('mixed.pdf'):'',{workerUrl:base+'/pdf.worker.min.js',cMapUrl:base+'/cmaps/'});
 const labels=useMemo(()=>({0:[{id:'first',label:[10,20,100,50],active}]}),[active]);
 const name=mode==='docx'?'sample.docx':mode==='markdown'?'sample.md':mode==='html'?'sample.html':mode==='media'?'sample.wav':mode==='image'?'image.svg':mode==='failed'?'missing.txt':'sample.txt';
 const resource={originalUrl:url(name),previewUrl:url(name)};
 const props={resource,locale};
 const services={scopeKey:scope,localize:(key:string,options?:any)=>String(instance.t(key,options)),getCitationDetail:async()=>null,resolveCitationDetails:async()=>[],getCitationUnresolvedReason:()=>undefined,resolveDocumentUrls:async()=>({originalUrl:url('sample.docx'),previewUrl:url('sample.docx')}),download:(href:string)=>global.__checks.downloads.push(href),openArticle:()=>{}};
 global.__checks.mode=mode;global.__checks.pdfPages=pdf.document?.numPages??0;
 return <main style={{padding:16,fontFamily:'sans-serif',maxWidth:880}}>
  <nav style={{display:'flex',flexWrap:'wrap',gap:8}}>{['pdf','edit','docx','markdown','text','html','image','csv','media','diagrams','reference','failed'].map(item=><button data-case={item} key={item} onClick={()=>setMode(item)}>{item}</button>)}</nav>
  <nav style={{display:'flex',gap:8,margin:'12px 0'}}>{['en','zh-Hans','ja'].map(lang=><button key={lang} data-lang={lang} onClick={()=>instance.changeLanguage(lang)}>{lang}</button>)}<button data-zoom onClick={()=>setZoom(150)}>150%</button><button data-scope onClick={()=>setScope(scope==='A'?'B':'A')}>scope</button></nav>
  <section data-viewer style={{height:440,width:'100%',display:'flex',minHeight:0,border:'1px solid #ddd',position:'relative',overflow:'hidden'}}>
   {mode==='pdf'&&<PdfViewer pdfDoc={pdf.document} zoomLevel={zoom} targetPage={null} onCurrentPageChange={()=>{}} loadingText={locale.loading} onRenderError={error=>global.__checks.errors.push(String(error))}/>}
   {mode==='edit'&&__PLATFORM_EDITOR__}
   {mode==='docx'&&<DocxViewer {...props}/>}
   {mode==='markdown'&&<MarkdownViewer {...props}/>}
   {(mode==='text'||mode==='failed')&&<TextViewer {...props}/>}
   {mode==='html'&&<HtmlViewer {...props}/>}
   {mode==='image'&&<ImageViewer {...props}/>}
   {mode==='csv'&&<ExcelPreview filePath={url('sample.csv')}/>}
   {mode==='media'&&<MediaViewer {...props} kind="audio"/>}
   {mode==='diagrams'&&<Diagrams/>}
   {mode==='reference'&&<CitationDocumentPreview preview={{detail:{citationId:'knowledgeSearch_fixture',type:'knowledgeSearch',sourcePayload:{documentName:'sample.docx',items:[{itemId:'a',content:'Shared DOCX target paragraph for citation locating.'}]}},itemId:'a',locateChunk:true}} services={services} renderFile={file=><DocxViewer resource={{originalUrl:file.fileUrl,previewUrl:file.fileUrl}} locale={locale}/>}/>}
  </section>
  <output data-ready>ready</output>
 </main>;
}
instance.init({lng:'en',fallbackLng:'en',resources:{en:{shared:en},'zh-Hans':{shared:zh},ja:{shared:ja}},defaultNS:'shared'}).then(()=>createRoot(document.getElementById('root')!).render(<I18nextProvider i18n={instance}><App/></I18nextProvider>));
