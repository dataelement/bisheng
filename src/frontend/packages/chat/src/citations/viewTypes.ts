import type { ReactNode } from 'react';
import type { PreviewPdfBBox } from '@bisheng/file-viewers/types';
import type { CitationServices } from './types';
export interface CitationFileProps {
  fileName:string;fileType:string;fileUrl:string;transcriptUrl?:string;
  highlightBboxes:PreviewPdfBBox[];targetBBox:PreviewPdfBBox|null;
  compactMode:boolean;allowDownload:boolean;onDownloadFile:()=>void;
}
export interface CitationViewProps {
  services:CitationServices;
  renderFile:(props:CitationFileProps)=>ReactNode;
  isNarrowLayout?:boolean;
  onMobileNavVisibility?:(hidden:boolean)=>void;
  onUnavailable?:(message:string)=>void;
}
