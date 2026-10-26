import { lazy,Suspense,useMemo } from 'react';
import type { CitationFileProps } from '@bisheng/chat/citation-views';
import { usePreviewLocale } from '@bisheng/file-viewers/locale';
import { TextViewer } from '@bisheng/file-viewers/text';
import { MarkdownViewer } from '@bisheng/file-viewers/markdown';
import { HtmlViewer } from '@bisheng/file-viewers/html-viewer';
import { ImageViewer } from '@bisheng/file-viewers/image';
import { MediaViewer } from '@bisheng/file-viewers/media';
import { PlatformPdfPreview } from '../preview/PlatformPdfPreview';
import { checkSassUrl } from '../preview/previewUrl';
import type { PdfLabels } from '../preview/pdfEditing';
const DocxViewer=lazy(()=>import('@bisheng/file-viewers/docx').then(module=>({default:module.DocxViewer})));
const ExcelPreview=lazy(()=>import('@bisheng/file-viewers').then(module=>({default:module.ExcelPreview})));
export function PlatformCitationFile({fileName,fileType,fileUrl,transcriptUrl,highlightBboxes,targetBBox,allowDownload}:CitationFileProps) {
 const locale=usePreviewLocale();
 const labels=useMemo(()=>highlightBboxes.reduce<PdfLabels>((map,box,index)=>{(map[box.page+1]??=[]).push({id:String(index),label:box.bbox,active:true});return map;},{}),[highlightBboxes]);
 const target=useMemo<[number,number]|undefined>(()=>targetBBox?[targetBBox.page+1,targetBBox.bbox[1]]:undefined,[targetBBox]);
 const viewerUrl=checkSassUrl(fileUrl);
 const props={resource:{originalUrl:viewerUrl,previewUrl:viewerUrl,fileName,fileType},locale};
 let body;
 switch(fileType.toLowerCase()) {
  case 'pdf':case 'ofd':body=<PlatformPdfPreview fileUrl={fileUrl} labels={labels} scrollTo={target}/>;break;
  case 'doc':case 'docx':body=<DocxViewer {...props}/>;break;
  case 'xlsx':case 'xls':case 'csv':body=<ExcelPreview filePath={fileUrl}/>;break;
  case 'md':case 'markdown':body=<MarkdownViewer {...props}/>;break;
  case 'html':case 'htm':body=<HtmlViewer {...props}/>;break;
  case 'png':case 'jpg':case 'jpeg':case 'gif':case 'bmp':case 'webp':body=<ImageViewer {...props}/>;break;
  case 'mp3':case 'wav':case 'm4a':case 'aac':case 'flac':case 'ogg':case 'mp4':case 'mov':case 'avi':case 'mkv':case 'webm':
   body=<MediaViewer {...props} resource={{...props.resource,originalUrl:fileUrl,previewUrl:transcriptUrl||''}} allowDownload={allowDownload} kind={['mp4','mov','avi','mkv','webm'].includes(fileType.toLowerCase())?'video':'audio'}/>;break;
  case 'txt':body=<TextViewer {...props}/>;break;
  default:body=<div className="flex h-full items-center justify-center text-text-3">{locale.unsupported}</div>;
 }
 return <Suspense fallback={<div>{locale.loading}</div>}><div className="flex h-full min-h-0 flex-1 flex-col overflow-hidden">{body}</div></Suspense>;
}
export function renderPlatformCitationFile(props:CitationFileProps){return <PlatformCitationFile {...props}/>;}
