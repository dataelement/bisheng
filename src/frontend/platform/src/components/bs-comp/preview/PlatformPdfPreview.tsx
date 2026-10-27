import { useCallback, useEffect, useRef, useState, type MouseEvent } from 'react';
import { VariableSizeList, type ListChildComponentProps, type ListOnScrollProps } from 'react-window';
import { useTranslation } from 'react-i18next';
import { PdfPage, usePdfDocument, pageLayout, type PageLayout, type PageSize, type PdfPageMetrics } from '@bisheng/file-viewers/pdf';
import type { PDFDocumentProxy } from 'pdfjs-dist';
import { LoadingIcon } from '../../bs-icons/loading';
import { checkSassUrl } from './previewUrl';
import { selectedLabels, type PdfLabels } from './pdfEditing';

export interface PdfScrollContext { startIndex: number; layout: PageLayout[] }
interface FileViewProps {
  startIndex?: number; drawfont?: boolean; select?: boolean; scrollTo?: [number, number];
  fileUrl: string; labels?: PdfLabels;
  onPageChange?: (offset: number, height: number, paperSize: number, scale: number, context?: PdfScrollContext) => void;
  onSelectLabel?: (rows: {id:string;active:boolean}[]) => void;
}
interface RowData {
  document: PDFDocumentProxy; width: number; drawfont: boolean; select: boolean;
  labels: PdfLabels; startIndex: number;
  onMetrics: (metrics: PdfPageMetrics) => void;
  onError: (error: unknown) => void;
  onSelectLabel?: FileViewProps['onSelectLabel'];
}
function PdfRow({ index, style, data }: ListChildComponentProps<RowData>) {
  const rows = data.labels[index + data.startIndex] ?? [];
  return <div style={style} className="border-b-2 bg-white overflow-hidden">
    <PdfPage pdfDoc={data.document} pageIndex={index} width={data.width} pixelRatio={2.5}
      drawText={data.drawfont} drawAnnotations onMetrics={data.onMetrics} onError={data.onError}
      renderOverlay={metrics => { const seen = new Set<string>(); return rows.length > 0 && <svg className="absolute inset-0 z-30" width={metrics.width} height={metrics.height}>
        {rows.map(row => {
          const key = row.label.join('-');
          if (seen.has(key) || row.label.length !== 4) return null;
          seen.add(key);
          const [x,y,x2,y2] = row.label;
          return <rect key={row.id} x={x*metrics.scale} y={y*metrics.scale} width={(x2-x)*metrics.scale} height={(y2-y)*metrics.scale}
            style={row.active ? {fill:'rgba(255, 236, 61, 0.2)',strokeWidth:1,stroke:'#ffec3d'} : {fill:'transparent',strokeWidth:1,stroke:'#666',strokeDasharray:4}}
            className={data.select ? 'cursor-pointer' : undefined}
            onClick={() => data.select && data.onSelectLabel?.([{id:row.id,active:!row.active}])} />;
        })}
      </svg>; }} />
  </div>;
}

export function PlatformPdfPreview({startIndex=1,drawfont=false,select=false,scrollTo,fileUrl,labels={},onPageChange,onSelectLabel}:FileViewProps) {
  const {t} = useTranslation('knowledge');
  const viewport = useRef<HTMLDivElement>(null);
  const list = useRef<VariableSizeList<RowData>>(null);
  const [size,setSize] = useState({width:0,height:0});
  const session = usePdfDocument(checkSassUrl(fileUrl), {workerUrl:__APP_ENV__.BASE_URL+'/pdf.worker.min.js',cMapUrl:__APP_ENV__.BASE_URL+'/cmaps/'});
  const pdf = session.document;
  const dimensions = useRef<{document:typeof pdf;sizes:Map<number,PageSize>}>({document:null,sizes:new Map()});
  if (dimensions.current.document !== pdf) dimensions.current = {document:pdf,sizes:new Map()};
  const [,setRevision] = useState(0);
  const [renderError,setRenderError] = useState<PDFDocumentProxy|null>(null);
  const currentDocument = useRef(pdf); currentDocument.current=pdf;
  const offset = useRef(0);
  const scrollTicket = useRef(0);
  const callbacks = useRef({onPageChange,onSelectLabel}); callbacks.current={onPageChange,onSelectLabel};
  useEffect(()=>{
    const element=viewport.current;
    if (!element) return;
    const measure=()=>setSize({width:element.clientWidth,height:element.clientHeight});
    measure();
    const observer=new ResizeObserver(measure); observer.observe(element);
    return ()=>observer.disconnect();
  },[]);
  const layout = pageLayout(Array.from({length:pdf?.numPages??0},(_,index)=>dimensions.current.sizes.get(index)??{width:595.32,height:841.92}),size.width);
  const layoutRef=useRef(layout);layoutRef.current=layout;
  const handleMetrics=useCallback((metrics:PdfPageMetrics)=>{
    if (!pdf || currentDocument.current!==pdf) return;
    const old=dimensions.current.sizes.get(metrics.pageIndex);
    if (old?.width===metrics.originalWidth && old.height===metrics.originalHeight) return;
    dimensions.current.sizes.set(metrics.pageIndex,{width:metrics.originalWidth,height:metrics.originalHeight});
    setRevision(value=>value+1);
    list.current?.resetAfterIndex(metrics.pageIndex);
  },[pdf]);
  const handleError=useCallback(()=>{if(pdf && currentDocument.current===pdf)setRenderError(pdf);},[pdf]);
  useEffect(()=>{list.current?.resetAfterIndex(0);},[pdf,size.width]);
  const targetPage=scrollTo?.[0];const targetY=scrollTo?.[1];
  useEffect(()=>{
    if(!pdf || !size.width || targetPage===undefined || targetY===undefined)return;
    const index=targetPage-startIndex;
    if(!Number.isInteger(index)||index<0||index>=pdf.numPages)return;
    const ticket=++scrollTicket.current;
    let active=true;
    void(async()=>{
      // Previous page dimensions are required for precise mixed-size document offsets.
      for(let pageIndex=0;pageIndex<=index;pageIndex++){
        if(!active||ticket!==scrollTicket.current)return;
        if(dimensions.current.sizes.has(pageIndex))continue;
        const page=await pdf.getPage(pageIndex+1);
        if(!active||ticket!==scrollTicket.current)return;
        const original=page.getViewport({scale:1});
        dimensions.current.sizes.set(pageIndex,{width:original.width,height:original.height});
      }
      if(!active||currentDocument.current!==pdf||ticket!==scrollTicket.current)return;
      const exact=pageLayout(Array.from({length:pdf.numPages},(_,i)=>dimensions.current.sizes.get(i)??{width:595.32,height:841.92}),size.width);
      setRevision(value=>value+1);list.current?.resetAfterIndex(0);
      list.current?.scrollTo(Math.max(0,exact[index].top+targetY*exact[index].scale-100));
    })().catch(()=>{if(active && currentDocument.current===pdf)handleError();});
    return()=>{active=false;};
  },[pdf,size.width,targetPage,targetY,startIndex,handleError]);
  const handleScroll=({scrollOffset,scrollUpdateWasRequested}:ListOnScrollProps)=>{
    offset.current=scrollOffset;
    if(!scrollUpdateWasRequested)scrollTicket.current++;
    const first=layoutRef.current[0];
    if(first)callbacks.current.onPageChange?.(scrollOffset,size.height,first.height,1/first.scale,{startIndex,layout:layoutRef.current});
  };
  const drag=useRef<{x:number;y:number;clientX:number;clientY:number}|null>(null);
  const suppressClick=useRef(false);
  const [selection,setSelection]=useState<{x:number;y:number;width:number;height:number}|null>(null);
  const handleMouseDown=(event:MouseEvent<HTMLDivElement>)=>{
    suppressClick.current=false;
    if(!select || event.button!==0 || !(event.target instanceof Element) || !event.target.closest('[data-pdf-page]'))return;
    const rect=viewport.current?.getBoundingClientRect();if(!rect)return;
    drag.current={x:event.clientX-rect.left,y:event.clientY-rect.top+offset.current,clientX:event.clientX,clientY:event.clientY};
  };
  useEffect(()=>{
    const move=(event:globalThis.MouseEvent)=>{
      const start=drag.current;const rect=viewport.current?.getBoundingClientRect();if(!start||!rect)return;
      const end={x:event.clientX-rect.left,y:event.clientY-rect.top+offset.current};
      const moved=Math.abs(event.clientX-start.clientX)+Math.abs(event.clientY-start.clientY)>3;
      if(moved){suppressClick.current=true;setSelection({x:Math.min(start.x,end.x),y:Math.min(start.y,end.y)-offset.current,width:Math.abs(start.x-end.x),height:Math.abs(start.y-end.y)});}
    };
    const up=(event:globalThis.MouseEvent)=>{
      const start=drag.current;drag.current=null;setSelection(null);
      const rect=viewport.current?.getBoundingClientRect();if(!start||!rect||!suppressClick.current||!select)return;
      const rows=selectedLabels(labels,startIndex,layoutRef.current,start,{x:event.clientX-rect.left,y:event.clientY-rect.top+offset.current});
      if(rows.length)callbacks.current.onSelectLabel?.(rows);
    };
    window.addEventListener('mousemove',move);window.addEventListener('mouseup',up);
    return()=>{drag.current=null;window.removeEventListener('mousemove',move);window.removeEventListener('mouseup',up);};
  },[labels,startIndex,select,pdf]);
  const rowData:RowData={document:pdf!,width:size.width,drawfont,select,labels,startIndex,onMetrics:handleMetrics,onError:handleError,onSelectLabel};
  return <div className="flex h-full min-h-0 w-full flex-col overflow-hidden bg-gray-100 rounded-md py-4 px-2 relative" onContextMenu={event=>event.preventDefault()}>
    <div ref={viewport} className="file-view relative flex-1 min-h-0 overflow-hidden" onMouseDown={handleMouseDown}
      onClickCapture={event=>{if(suppressClick.current){event.stopPropagation();suppressClick.current=false;}}}>
      {session.status==='loading' ? <div className="absolute inset-0 flex justify-center items-center"><LoadingIcon /></div>
        : session.status==='error'||renderError===pdf&&pdf!==null ? <div className="flex h-full w-full items-center justify-center text-gray-400">{t('file.previewNotAvailable')}</div>
        : pdf && size.width>0 && size.height>0 && <VariableSizeList ref={list} itemCount={pdf.numPages} itemSize={index=>layout[index].height}
          itemData={rowData} width={size.width} height={size.height} onScroll={handleScroll}>{PdfRow}</VariableSizeList>}
      {selection&&<div className="pointer-events-none absolute z-40 border-2 border-blue-500 bg-blue-100/25" style={{left:selection.x,top:selection.y,width:selection.width,height:selection.height}} />}
    </div>
  </div>;
}
