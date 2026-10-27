import { containsBBox, scaleBBox, type PageLayout } from '@bisheng/file-viewers/pdf';
export interface PdfLabel { id: string; label: number[]; active: boolean }
export type PdfLabels = Record<string | number, PdfLabel[]>;
export function selectedLabels(labels: PdfLabels, start: number, layout: PageLayout[], a: {x:number;y:number}, b: {x:number;y:number}): {id:string;active:boolean}[] {
  const box = {x:Math.min(a.x,b.x),y:Math.min(a.y,b.y),width:Math.abs(b.x-a.x),height:Math.abs(b.y-a.y)};
  const result: {id:string;active:boolean}[] = [];
  for (const [page, rows] of Object.entries(labels)) {
    const metrics = layout[Number(page)-start];
    if (!metrics) continue;
    for (const row of rows) {
      if (row.label.length !== 4) continue;
      const bounds = scaleBBox(row.label as [number,number,number,number],metrics.scale);
      if (containsBBox(box,{...bounds,y:bounds.y+metrics.top})) result.push({id:row.id,active:!row.active});
    }
  }
  return result;
}
export function labelTop(page:number,y:number,start:number,layout:PageLayout[]):number|null {
  const metrics=layout[page-start];
  return metrics ? metrics.top+y*metrics.scale : null;
}
