import yaml from 'js-yaml';

export const PERSONAL_TEMPLATE_PROFILE_VERSION = 1;
const colour = value => typeof value === 'string' && /^#?[a-f0-9]{6}(?:[a-f0-9]{2})?$/iu.test(value)
  ? value.replace('#', '').slice(0, 6).toUpperCase() : undefined;
const add = (map, value, weight) => { if (value !== undefined && weight > 0) map.set(value, (map.get(value) ?? 0) + weight); };
const ranked = map => [...map].sort((a, b) => b[1] - a[1]).map(([value]) => value);
const pick = (map, fallback) => ranked(map)[0] ?? fallback;
const chromatic = value => {
  const channels = [0, 2, 4].map(i => parseInt(value.slice(i, i + 2), 16));
  return Math.max(...channels) - Math.min(...channels) > 35;
};
const plainText = content => content.paragraphs?.length
  ? content.paragraphs.map(p => (p.runs ?? []).map(r => r.text ?? '').join('')).join('\n').trim()
  : String(content.text ?? '').replace(/<[^>]*>/gu, '').trim();
function textStyle(content) {
  const runs = (content.paragraphs ?? []).flatMap(p => p.runs ?? []);
  const faces = new Map(), sizes = new Map(), colors = new Map(), weights = new Map();
  for (const run of runs) {
    const weight = String(run.text ?? '').trim().length;
    add(faces, run.options?.fontFamily ?? content.fontFamily, weight);
    add(sizes, run.options?.fontSize ?? content.fontSize, weight);
    add(colors, colour(run.options?.color ?? content.color), weight);
    add(weights,run.options?.bold ?? content.bold ?? false,weight);
  }
  return {fontFace:pick(faces,content.fontFamily ?? 'Arial'),fontSize:pick(sizes,content.fontSize ?? 18),color:pick(colors,colour(content.color) ?? '000000'),bold:pick(weights,content.bold ?? false)};
}

/** Derive reusable layout facts from the checked model. Role labels are geometry
 * heuristics; source content and native layout stay intact for preview and editing.
 * @param {import('./types/pptd.js').PptdProject} project
 * @returns {import('./types/personal-template-profile.js').PersonalTemplateProfile}
 */
export function extractPersonalTemplateProfile(project) {
  const backgrounds=new Map(), surfaces=new Map(), inks=new Map(), accents=new Map();
  const headingFaces=new Map(), bodyFaces=new Map(), headingSizes=new Map(), bodySizes=new Map();
  const headingColors=new Map(),bodyColors=new Map(),headingWeights=new Map(),bodyWeights=new Map(),mutedColors=new Map();
  const occurrences=new Map();
  const area=project.width*project.height;
  for (const page of project.pages) for (const element of page.elements) if (element.elementType==='text') {
    const text=plainText(element.content ?? {});
    if(text) {const files=occurrences.get(text) ?? new Set();files.add(page.file);occurrences.set(text,files);}
  }
  const pages=project.pages.map((page,index)=>{
    add(backgrounds,colour(page.background?.color),1);
    const texts=page.elements.filter(e=>e.elementType==='text' && plainText(e.content ?? {}));
    const styles=new Map(texts.map(e=>[e,textStyle(e.content ?? {})]));
    // The largest upper-page text block establishes hierarchy without relying on its wording.
    const title=texts.filter(e=>e.bounds[1]<project.height*.55)
      .sort((a,b)=>styles.get(b).fontSize-styles.get(a).fontSize || a.bounds[1]-b.bounds[1])[0];
    const slots=[];
    for (const element of page.elements) {
      const bounds=element.bounds;
      if(!Array.isArray(bounds)||bounds.length!==4)continue;
      const [x,y,width,height]=bounds;
      const fill=colour(element.fill?.color);
      if(fill) {
        const weight=Math.min(width*height/area,.25);
        add(surfaces,fill,weight);
        if(chromatic(fill))add(accents,fill,weight);
      }
      if(element.elementType==='text') {
        const content=element.content ?? {}, text=plainText(content),style=styles.get(element);
        if(!text||!style)continue;
        const edge=y>project.height*.86 || (height<project.height*.12 && (x+width<project.width*.2 || x>project.width*.8));
        const repeated=(occurrences.get(text)?.size ?? 0)>=Math.min(3,project.pages.length) && project.pages.length>1;
        const role=element===title?'title':edge?'footer':'body';
        const chars=Math.max(1,text.length);
        if(role==='title') {add(headingFaces,style.fontFace,chars);add(headingSizes,style.fontSize,chars);add(headingColors,style.color,chars);add(headingWeights,style.bold,chars);}
        else if(role==='body') {add(bodyFaces,style.fontFace,chars);add(bodySizes,style.fontSize,chars);add(inks,style.color,chars);add(bodyColors,style.color,chars);add(bodyWeights,style.bold,chars);}
        else add(mutedColors,style.color,chars);
        if(chromatic(style.color))add(accents,style.color,Math.min(chars/100,.25));
        const margins=content.margins ?? [0,0,0,0];
        const usableWidth=Math.max(0,width-(margins[1] ?? 0)-(margins[3] ?? 0));
        const usableHeight=Math.max(0,height-(margins[0] ?? 0)-(margins[2] ?? 0));
        slots.push({elementId:element.elementId,kind:'text',role,action:edge&&repeated?'review-branding':'replace-content',bounds:[...bounds],
          ...style,wrap:content.wrap!==false,fit:content.fit ?? 'source',
          // A full-width character estimate, for authoring guidance rather than automatic truncation.
          textCapacity:Math.max(1,Math.floor(usableWidth/style.fontSize)*Math.max(1,Math.floor(usableHeight/(style.fontSize*1.2))))});
      } else if(['image','chart','table'].includes(element.elementType)) {
        const background=width*height/area>.85;
        const cue=element.elementId?.includes('background');
        slots.push({elementId:element.elementId,kind:element.elementType,role:background&&cue?'background':element.elementType,
          action:background&&cue?'review-branding':'replace-content',bounds:[...bounds]});
      }
    }
    const body=slots.filter(s=>s.role==='body');
    const visuals=slots.filter(s=>['image','chart','table'].includes(s.role));
    const role=index===0?'cover':visuals.some(s=>s.kind==='chart'||s.kind==='table')?'data':visuals.some(s=>s.bounds[2]*s.bounds[3]/area>.3)?'visual':body.length>1?'multi-block':'content';
    return {slideNumber:index+1,file:page.file,role,roleBasis:'geometry',slots};
  });
  const background=pick(backgrounds,'FFFFFF'),text=pick(inks,'222222');
  const palette={background,surface:ranked(surfaces).find(c=>c!==background) ?? 'F4F4F4',text,
    muted:pick(mutedColors,ranked(inks).find(c=>c!==text&&!chromatic(c)) ?? '666666'),accent:pick(accents,text),
    secondary:ranked(accents)[1] ?? pick(accents,'AAAAAA')};
  return {version:PERSONAL_TEMPLATE_PROFILE_VERSION,canvas:{width:project.width,height:project.height},palette,
    typography:{title:{fontFace:pick(headingFaces,'Arial'),fontSize:pick(headingSizes,36),color:pick(headingColors,text),bold:pick(headingWeights,true)},
      body:{fontFace:pick(bodyFaces,pick(headingFaces,'Arial')),fontSize:pick(bodySizes,18),color:pick(bodyColors,text),bold:pick(bodyWeights,false)}},pages};
}

/** Copy the source plane with its extracted theme; explicit per-object styles retain precedence. */
export function personalTemplateSourceTheme(source,profile) {
  const manifest=yaml.load(source.manifest,{schema:yaml.JSON_SCHEMA});
  const style=(value)=>({fontFamily:value.fontFace,fontSize:value.fontSize,color:'#'+value.color,bold:value.bold});
  manifest.theme={...manifest.theme,colors:{...manifest.theme?.colors,primary:'#'+profile.palette.accent,...Object.fromEntries(Object.entries(profile.palette).map(([key,value])=>[key,'#'+value]))},
    textStyles:{...manifest.theme?.textStyles,title:style(profile.typography.title),body:style(profile.typography.body)}};
  return {...source,manifest:yaml.dump(manifest,{noRefs:true,lineWidth:-1})};
}

/** Bounded, content-free layout guidance for agent tools and copied template projects. */
export function personalTemplatePageSummary(page,detailed=false) {
  const slotCounts={};
  for(const slot of page.slots)slotCounts[slot.role]=(slotCounts[slot.role] ?? 0)+1;
  return JSON.stringify({role:page.role,roleBasis:page.roleBasis,slotCounts,...detailed?{slots:page.slots}:{}});
}
export function personalTemplateDesignProfile(template) {
  const profile=template.templateProfile;
  if(!profile)return '';
  return [`画布：${profile.canvas.width} × ${profile.canvas.height} pt。`,
    `字体：标题 ${profile.typography.title.fontFace} ${profile.typography.title.fontSize} pt；正文 ${profile.typography.body.fontFace} ${profile.typography.body.fontSize} pt。`,
    `配色：${Object.entries(profile.palette).map(([role,value])=>`${role} #${value}`).join('；')}。`,
    `可复用页型（按几何推断）：${[...new Set(profile.pages.map(p=>p.role))].join('、')}。`,
    ...(template.templateSamples ? [`模板示例：${template.templateSamples.representativePages.length} 个代表版式，共 ${profile.pages.length} 页可编辑页面。文字示例和页面结构共用实际工程；图表、表格和密集图示保留原数据，按当前任务逐项替换。`] : []),
    '通过 ppt_get_template_pages 读取元素 ID、位置、字体和文字容量估计，选择适合本次内容的页面。替换内容后核对换行与留白；重复边缘文字和背景素材按品牌需要保留。'].join('\n');
}

/** Validate persisted metadata before projecting it into agent tools. Older records
 * can omit this profile and receive it on their next cached upload.
 */
export function validPersonalTemplateProfile(profile,pageIndex) {
  const font=value=>typeof value?.fontFace==='string' && Number.isFinite(value.fontSize) && value.fontSize>0 && colour(value.color)===value.color && typeof value.bold==='boolean';
  const positive=value=>Number.isFinite(value)&&value>0;
  return !!profile && Number.isInteger(profile.version) && profile.version>0
    && positive(profile.canvas?.width) && positive(profile.canvas?.height)
    && ['background','surface','text','muted','accent','secondary'].every(role=>colour(profile.palette?.[role])===profile.palette?.[role] && typeof profile.palette?.[role]==='string')
    && font(profile.typography?.title) && font(profile.typography?.body)
    && Array.isArray(profile.pages) && profile.pages.length===pageIndex.length
    && profile.pages.every((page,index)=>page?.slideNumber===index+1 && page.file===pageIndex[index].file && page.roleBasis==='geometry'
      && ['cover','content','multi-block','data','visual'].includes(page.role) && Array.isArray(page.slots)
      && page.slots.every(slot=>typeof slot?.elementId==='string' && ['text','image','chart','table'].includes(slot.kind)
        && ['title','body','footer','background','image','chart','table'].includes(slot.role)
        && ['replace-content','review-branding'].includes(slot.action)
        && Array.isArray(slot.bounds) && slot.bounds.length===4 && slot.bounds.every(Number.isFinite)
        && (slot.kind!=='text' || (font(slot) && typeof slot.wrap==='boolean' && typeof slot.fit==='string' && positive(slot.textCapacity)))));
}
