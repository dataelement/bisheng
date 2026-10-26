// @vitest-environment jsdom
import { readFileSync } from 'node:fs';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { convertToHtml } from 'mammoth';
import { DocxViewer } from './DocxViewer';
import { TextViewer } from './TextViewer';
import { MarkdownViewer } from './MarkdownViewer';
import { HtmlViewer } from './HtmlViewer';
import { ImageViewer } from './ImageViewer';
import { MediaViewer } from './MediaViewer';
import type { PreviewLocale } from '../viewerTypes';
vi.mock('mammoth', () => ({ convertToHtml: vi.fn() }));
const locale: PreviewLocale = {fileExpired:"File expired", media:{download:"download",exit_fullscreen:"exit_fullscreen",fullscreen:"fullscreen",more:"more",mute:"mute",pause:"pause",picture_in_picture:"picture_in_picture",play:"play",playback_speed:"playback_speed",progress:"progress",unmute:"unmute",volume:"volume"}, select:{emptyText:"Empty",noMatchText:"No match",loadingText:"Loading",clearLabel:"Clear",removeLabel:"Remove"}, loading:'Loading',docLoading:'Loading document',failed:'Preview failed',empty:'Empty',imageAlt:'Image preview',htmlTitle:'HTML preview',unsupported:'Unsupported',recognizedText:'Recognized',entryText:'Indexed' };
const resource = { originalUrl:'/original', previewUrl:'/preview' };
const fetchFile = vi.fn();
beforeEach(() => {
  vi.stubGlobal('fetch', fetchFile);
  fetchFile.mockReset();
  fetchFile.mockResolvedValue({ ok:true, text:async ()=>'content', arrayBuffer:async()=>new ArrayBuffer(1) });
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });
it('shows text literally and does not execute embedded markup', async () => {
  fetchFile.mockResolvedValueOnce({ ok:true,text:async()=>'<img src=x onerror="alert(1)">\nsecond' });
  const view=render(<TextViewer resource={resource} locale={locale} />);
  await screen.findByText(/second/);
  expect(view.container.querySelector('img')).toBeNull();
  expect(view.container.querySelector('pre')?.textContent).toBe('<img src=x onerror="alert(1)">\nsecond');
});
it('renders fenced code with exactly the original line breaks', async () => {
  fetchFile.mockResolvedValueOnce({ok:true,text:async()=> '```python\nx = 1\ny = 2\n```'});
  const view=render(<MarkdownViewer resource={resource} locale={locale} />);
  await waitFor(()=>expect(view.container.querySelector('pre code')).not.toBeNull());
  expect(view.container.querySelector('pre code')?.textContent).toBe('x = 1\ny = 2\n');
});
it('sanitizes converted DOCX while retaining tables and images', async () => {
  vi.mocked(convertToHtml).mockResolvedValueOnce({value:'<table><tr><td>Cell</td></tr></table><img src="/picture" onerror="alert(1)"><script>alert(1)</script>',messages:[]});
  const view=render(<DocxViewer resource={resource} locale={locale} />);
  await screen.findByText('Cell');
  expect(view.container.querySelector('table')).not.toBeNull();
  expect(view.container.querySelector('img')?.getAttribute('src')).toBe('/picture');
  expect(view.container.querySelector('img')?.getAttribute('onerror')).toBeNull();
  expect(view.container.querySelector('script')).toBeNull();
});
it('keeps HTML inside an opaque sandbox with the storage shim', async () => {
  fetchFile.mockResolvedValueOnce({ok:true,text:async()=> '<!doctype html><html><head></head><body>Deck</body></html>'});
  render(<HtmlViewer resource={resource} locale={locale} />);
  const frame=await screen.findByTitle('HTML preview');
  expect(frame.getAttribute('sandbox')?.split(' ')).toContain('allow-scripts');
  expect(frame.getAttribute('sandbox')?.split(' ')).not.toContain('allow-same-origin');
  expect(frame.getAttribute('srcdoc')).toContain('__bs_probe__');
});
it('uses local failure copy without exposing the raw fetch exception', async () => {
  fetchFile.mockRejectedValueOnce(new Error('PRIVATE stack'));
  render(<TextViewer resource={resource} locale={locale} />);
  await screen.findByText('Preview failed');
  expect(screen.queryByText(/PRIVATE/)).toBeNull();
});
it('reports an unavailable image with the current local failure copy', async () => {
  render(<ImageViewer resource={resource} locale={locale} />);
  fireEvent.error(screen.getByAltText('Image preview'));
  await screen.findByText('Preview failed');
});
it('plays the original clip while loading the derived transcript, with separate text tabs', async () => {
  const transcript=readFileSync('src/viewers/fixtures/transcript.md','utf8');
  fetchFile.mockResolvedValueOnce({ok:true,text:async()=>transcript});
  const view=render(<MediaViewer resource={{...resource,fileType:'mp4'}} kind="video" locale={locale} />);
  expect(view.container.querySelector('video')?.getAttribute('src')).toBe('/original');
  await screen.findByText('Spoken transcript continued cue');
  expect(fetchFile.mock.calls[0][0]).toBe('/preview');
  fireEvent.click(screen.getByRole('button',{name:'Indexed'}));
  await screen.findByText('Indexed knowledge paragraph');
  expect(screen.queryByText('Spoken transcript continued cue')).toBeNull();
});
it('keeps protected-file failure evidence for the host while showing safe copy', async () => {
  const response = { ok:false,status:403 };
  fetchFile.mockResolvedValueOnce(response);
  const onError = vi.fn();
  render(<TextViewer resource={resource} locale={locale} onError={onError} />);
  await screen.findByText('Preview failed');
  await waitFor(()=>expect(onError).toHaveBeenCalledWith(expect.objectContaining({status:403,response})));
});
it('retains playback, keyboard seeking and volume controls after extraction', async () => {
  const play = vi.spyOn(HTMLMediaElement.prototype,'play').mockResolvedValue(undefined);
  const view=render(<MediaViewer resource={{originalUrl:'/clip',previewUrl:''}} kind="video" locale={locale} />);
  const media=view.container.querySelector('video')!;
  Object.defineProperty(media,'duration',{configurable:true,value:10});
  fireEvent.loadedMetadata(media);
  fireEvent.click(screen.getByRole('button',{name:'play'}));
  expect(play).toHaveBeenCalledTimes(1);
  fireEvent.play(media);
  expect(screen.getByRole('button',{name:'pause'})).not.toBeNull();
  fireEvent.keyDown(screen.getByRole('slider',{name:'progress'}),{key:'ArrowRight'});
  expect(media.currentTime).toBe(0.5);
  fireEvent.keyDown(screen.getByRole('slider',{name:'volume'}),{key:'ArrowDown'});
  expect(media.volume).toBeCloseTo(0.95);
  fireEvent.click(screen.getByRole('button',{name:'mute'}));
  expect(media.muted).toBe(true);
});

it('retries an image after selecting another resource and returning to the failed image',()=>{
 const a={originalUrl:'/A.png',previewUrl:'/A.png'},b={originalUrl:'/B.png',previewUrl:'/B.png'};
 const view=render(<ImageViewer resource={a} locale={locale}/>);
 fireEvent.error(screen.getByAltText('Image preview'));expect(screen.getByText('Preview failed')).toBeTruthy();
 view.rerender(<ImageViewer resource={b} locale={locale}/>);fireEvent.load(screen.getByAltText('Image preview'));
 view.rerender(<ImageViewer resource={a} locale={locale}/>);
 expect(screen.getByAltText('Image preview').getAttribute('src')).toBe('/A.png');
});
it('retries playback after selecting another resource and returning to failed media',()=>{
 const a={originalUrl:'/A.mp4',previewUrl:''},b={originalUrl:'/B.mp4',previewUrl:''};
 const view=render(<MediaViewer resource={a} kind="video" locale={locale}/>);
 fireEvent.error(view.container.querySelector('video')!);expect(screen.getByText('Preview failed')).toBeTruthy();
 view.rerender(<MediaViewer resource={b} kind="video" locale={locale}/>);expect(view.container.querySelector('video')).not.toBeNull();
 view.rerender(<MediaViewer resource={a} kind="video" locale={locale}/>);
 expect(view.container.querySelector('video')?.getAttribute('src')).toBe('/A.mp4');
});
