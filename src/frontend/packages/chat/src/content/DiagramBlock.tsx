import { Button, Tooltip } from '@bisheng/ui';
import { Outlined } from 'bisheng-icons';
import { ZoomOut } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { CopyMessageAction } from '../components/CopyMessageAction';
import { useMarkdownServices } from './MarkdownServices';
import { downloadDiagram, normalizeMindmapIndent, readEchartsRuntime, readMermaidRuntime, type ChartInstance } from './diagramRuntime';
export function DiagramBlock({ language, code }: { language: 'mermaid' | 'echarts'; code: string }) {
  const { loadDiagramLibrary, localize, copyText, diagramTitle } = useMarkdownServices();
  const [mode, setMode] = useState<'chart' | 'code'>('chart');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const drag = useRef<{ x: number; y: number } | null>(null);
  const diagramRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    let active = true;
    let chart: ChartInstance | null = null;
    const node = diagramRef.current;
    if (!node) return;
    setLoading(true); setError(false);
    void loadDiagramLibrary(language).then(async value => {
      if (!active) return;
      if (language === 'mermaid') {
        const runtime = readMermaidRuntime(value);
        runtime.initialize({ startOnLoad: false, theme: 'default' });
        node.textContent = normalizeMindmapIndent(code);
        await runtime.run({ nodes: [node] });
      } else {
        const runtime = readEchartsRuntime(value);
        chart = runtime.init(node);
        // Preserve the client's existing executable ECharts-option contract.
        const getOption = new Function('myChart', 'echarts', `return ${code.trim()}`) as (chart: ChartInstance, runtime: unknown) => unknown;
        chart.setOption(getOption(chart, value));
      }
      if (active) setLoading(false);
    }).catch(reason => { if (active) { setError(true); setLoading(false); console.error('Diagram rendering failed:', reason); } });
    const resize = () => chart?.resize();
    const observer = typeof ResizeObserver === 'undefined' ? undefined : new ResizeObserver(resize);
    if (containerRef.current) observer?.observe(containerRef.current);
    window.addEventListener('resize', resize);
    return () => { active = false; chart?.dispose(); observer?.disconnect(); window.removeEventListener('resize', resize); };
  }, [code, language, loadDiagramLibrary]);
  const chartLabel = localize('shared:app_chat.chart');
  const codeLabel = localize('shared:app_chat.code');
  return <div className="w-full my-3" ref={containerRef}>
    <div className="shadow-sm rounded-lg bg-muted overflow-hidden">
      <div className="flex items-center justify-between p-2 relative z-10 bg-muted">
        <div className="flex gap-1 bg-background rounded-md">
          <Button variant={mode === 'chart' ? 'solid' : 'text'} color={mode === 'chart' ? 'primary' : 'default'} onClick={() => setMode('chart')}>{chartLabel}</Button>
          <Button variant={mode === 'code' ? 'solid' : 'text'} color={mode === 'code' ? 'primary' : 'default'} onClick={() => setMode('code')}>{codeLabel}</Button>
        </div>
        {mode === 'code' ? <CopyMessageAction label={localize('shared:app_chat.copy_code')} copiedLabel={localize('shared:app_chat.copied')} onCopy={() => copyText(code)} />
          : language === 'mermaid' && <div className="flex items-center">
            <Tooltip content={localize('shared:app_chat.zoom_out')}><Button iconOnly aria-label={localize('shared:app_chat.zoom_out')} color="default" variant="text" disabled={zoom <= 0.5} onClick={() => setZoom(value => Math.max(value - 0.2, 0.5))}><ZoomOut size={16} /></Button></Tooltip>
            <Tooltip content={localize('shared:app_chat.zoom_in')}><Button iconOnly aria-label={localize('shared:app_chat.zoom_in')} color="default" variant="text" disabled={zoom >= 3} onClick={() => setZoom(value => Math.min(value + 0.2, 3))}><Outlined.Plus size={16} /></Button></Tooltip>
            <Tooltip content={localize('shared:app_chat.download')}><Button iconOnly aria-label={localize('shared:app_chat.download')} color="default" variant="text" onClick={() => { if (diagramRef.current) void downloadDiagram(diagramRef.current, diagramTitle).catch(() => setError(true)); }}><Outlined.Download size={16} /></Button></Tooltip>
          </div>}
      </div>
      {mode === 'chart' && loading && <div className="flex items-center justify-center h-[400px] text-muted-foreground">{localize('shared:app_chat.loading')}</div>}
      {mode === 'chart' && error && <p role="alert" className="p-4 text-danger">{localize('shared:app_chat.diagram_failed')}</p>}
      <div className={mode === 'chart' ? 'block overflow-hidden' : 'hidden'}
        onPointerDown={event => { if (language === 'mermaid') { drag.current = { x: event.clientX - pan.x, y: event.clientY - pan.y }; event.currentTarget.setPointerCapture(event.pointerId); } }}
        onPointerMove={event => { if (drag.current) setPan({ x: event.clientX - drag.current.x, y: event.clientY - drag.current.y }); }}
        onPointerUp={() => { drag.current = null; }} onPointerCancel={() => { drag.current = null; }}>
        <div ref={diagramRef} className={language === 'mermaid' ? 'flex justify-center min-h-[100px]' : undefined}
          style={language === 'mermaid' ? { transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`, transformOrigin: 'center center' } : { height: 400 }} />
      </div>
      {mode === 'code' && <pre className="p-4 overflow-auto text-sm leading-relaxed max-h-[500px]"><code className="text-slate-500 font-mono whitespace-pre-wrap break-words">{code}</code></pre>}
    </div>
  </div>;
}
