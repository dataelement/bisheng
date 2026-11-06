import { describe, expect, it } from 'vitest';
import { selectedLabels, labelTop } from './pdfEditing';
const layout = [{top:0,height:400,scale:2},{top:400,height:100,scale:1}];
const labels = {0:[{id:'a',label:[10,20,30,40],active:false}],1:[{id:'b',label:[5,5,10,10],active:true}]};
describe('PDF host editing coordinates',()=>{
  it('normalizes a reverse drag across mixed-size pages using explicit zero-based metadata',()=>{
    expect(selectedLabels(labels,0,layout,{x:50,y:430},{x:0,y:0})).toEqual([{id:'b',active:false}]);
    expect(selectedLabels(labels,0,layout,{x:70,y:430},{x:0,y:0})).toEqual([{id:'a',active:true},{id:'b',active:false}]);
  });
  it('uses per-page offsets for one-based metadata and excludes partial intersections',()=>{
    expect(selectedLabels({1:labels[0]},1,layout,{x:21,y:41},{x:59,y:79})).toEqual([]);
    expect(labelTop(2,5,1,layout)).toBe(405);
    expect(labelTop(0,5,1,layout)).toBeNull();
  });
});
