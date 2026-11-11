/** Deterministic local SVG/PNG preview renderer for PPTD CLI screenshot workflows. */
import type { PptdProject } from './pptd.ts';
/** Render one PPTD page to a standalone SVG string without network access. */
export declare function renderPptdPageSvg(project: PptdProject, pageIndex: number): string;
/** Render one PPTD page to PNG bytes through the bundled local SVG rasterizer. */
export declare function renderPptdPagePng(project: PptdProject, pageIndex: number, scale?: number): Promise<Uint8Array>;