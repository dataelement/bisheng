import { expect, it } from 'vitest';
import { pageIndexFromMetadata, pageLayout, scaleBBox, containsBBox } from './coordinates';
it('converts explicit zero/one based metadata without guessing', () => {
  expect(pageIndexFromMetadata(0,0,2)).toBe(0);
  expect(pageIndexFromMetadata(1,1,2)).toBe(0);
  expect(pageIndexFromMetadata(2,1,2)).toBe(1);
  expect(pageIndexFromMetadata(2,0,2)).toBeNull();
  expect(pageIndexFromMetadata(-1,0,2)).toBeNull();
});
it('uses each page aspect ratio to locate mixed-size pages after resizing', () => {
  const sizes=[{width:100,height:200},{width:200,height:200}];
  expect(pageLayout(sizes,100).map(page=>[page.top,page.height,page.scale])).toEqual([[0,200,1],[200,100,0.5]]);
  expect(pageLayout(sizes,200).map(page=>[page.top,page.height,page.scale])).toEqual([[0,400,2],[400,200,1]]);
});
it('maps highlights with the same scale used by rendering and box selection', () => {
  const box=scaleBBox([10,20,60,40],2);
  expect(box).toEqual({x:20,y:40,width:100,height:40});
  expect(containsBBox({x:0,y:0,width:150,height:100},box)).toBe(true);
  expect(containsBBox({x:30,y:0,width:150,height:100},box)).toBe(false);
});
