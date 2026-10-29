import type { ReactNode } from 'react';
import type { PDFDocumentProxy } from 'pdfjs-dist';
export interface PdfPageMetrics {pageIndex:number;originalWidth:number;originalHeight:number;width:number;height:number;scale:number}
export interface PdfPageProps {pdfDoc:PDFDocumentProxy;pageIndex:number;width:number;zoomLevel?:number;drawText?:boolean;drawAnnotations?:boolean;pixelRatio?:number;onMetrics?:(metrics:PdfPageMetrics)=>void;onError?:(error:unknown)=>void;renderOverlay?:(metrics:PdfPageMetrics)=>ReactNode}
