const child = (node, name) => [...(node?.children ?? [])].find(item => item.localName === name);
/** Resolve literal and named guide coordinates into the existing PPTD vector path model. */
export function convertedGeometry(geometry, width, height) {
  if (!geometry) return undefined;
  const guides = new Map([['w',width],['h',height],['l',0],['t',0],['r',width],['b',height],['hc',width/2],['vc',height/2]]);
  const number = value => {
    const v = guides.has(value) ? guides.get(value) : Number(value);
    if (!Number.isFinite(v)) throw new Error(`Unsupported custom geometry coordinate: ${value}`);
    return v;
  };
  for (const list of ['avLst','gdLst']) for (const guide of [...(child(geometry,list)?.children ?? [])]) {
    const [op,...args] = guide.getAttribute('fmla').split(/\s+/), [a,b,c] = args.map(number);
    const value = op === 'val' ? a : op === '+-' ? a+b-c : op === '*/' ? a*b/c : op === '+/' ? (a+b)/c : op === 'min' ? Math.min(a,b) : op === 'max' ? Math.max(a,b) : op === 'abs' ? Math.abs(a) : op === 'sqrt' ? Math.sqrt(a) : op === '?:' ? (a>0?b:c) : NaN;
    if (!Number.isFinite(value)) throw new Error(`Unsupported custom geometry formula: ${op}`);
    guides.set(guide.getAttribute('name'),value);
  }
  const paths = [...(child(geometry,'pathLst')?.children ?? [])];
  if (!paths.length) throw new Error('Custom geometry has no paths');
  const commands = [];
  for (const path of paths) {
    const pw = number(path.getAttribute('w') ?? width), ph = number(path.getAttribute('h') ?? height);
    if (pw<=0 || ph<=0) throw new Error('Custom geometry has invalid dimensions');
    for (const command of [...path.children]) {
      const names = {moveTo:'M',lnTo:'L',cubicBezTo:'C',quadBezTo:'Q',close:'Z'};
      const name = names[command.localName];
      if (!name) throw new Error(`Unsupported custom geometry command: ${command.localName}`);
      const pts = [...command.children].map(pt => `${number(pt.getAttribute('x'))/pw*width} ${number(pt.getAttribute('y'))/ph*height}`);
      commands.push(name + ' ' + pts.join(' '));
    }
  }
  return {shapeName:'custom',viewBox:[width,height],path:commands.join(' ')};
}
