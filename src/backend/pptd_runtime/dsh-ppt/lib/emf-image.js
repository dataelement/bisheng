/** Bounded 2D EMF playback. Record layouts follow Microsoft's MS-EMF specification.
 * Vector paths, clipping, coordinates and solid GDI objects become self-contained SVG.
 * Unsupported drawing operations fail explicitly so imported pictures remain complete.
 */
const MAX_BYTES = 8 * 1024 * 1024;
const MAX_RECORDS = 20000;
const MAX_POINTS = 200000;
const invalid = message => { throw new Error(`EMF ${message}`); };
const num = n => { if (!Number.isFinite(n) || Math.abs(n) > 1e9) invalid('坐标超出范围'); return Number(n.toFixed(4)); };
const color = n => '#' + [n & 255, n >>> 8 & 255, n >>> 16 & 255].map(v => v.toString(16).padStart(2, '0')).join('');

export function emfToSvg(bytes) {
  const data = Buffer.from(bytes);
  if (data.length < 88 || data.length > MAX_BYTES || data.readUInt32LE(0) !== 1 || data.readUInt32LE(40) !== 0x464d4520) invalid('文件头无效');
  const headerSize = data.readUInt32LE(4), declaredBytes = data.readUInt32LE(48), declaredRecords = data.readUInt32LE(52);
  if (headerSize < 88 || headerSize > data.length || declaredBytes !== data.length || declaredRecords > MAX_RECORDS) invalid('文件长度无效');
  const [left, top, right, bottom] = [8, 12, 16, 20].map(o => data.readInt32LE(o));
  const width = right - left + 1, height = bottom - top + 1;
  if (width <= 0 || height <= 0 || width > 32768 || height > 32768) invalid('画布尺寸无效');
  const descriptionLength = data.readUInt32LE(60), descriptionOffset = data.readUInt32LE(64);
  if (descriptionLength && (descriptionOffset < 88 || descriptionOffset + descriptionLength * 2 > headerSize)) invalid('描述字段无效');
  // Description bytes belong to the variable tail, not to the optional OpenGL header.
  const fixedHeaderSize = descriptionLength ? descriptionOffset : headerSize;
  if (fixedHeaderSize >= 100 && data.readUInt32LE(96)) invalid('含暂未支持的 OpenGL 绘图');
  let state = { wx:0, wy:0, ww:1, wh:1, vx:0, vy:0, vw:1, vh:1, mode:1, x:0, y:0, fill:'#ffffff', pen:'#000000', penWidth:1, fillRule:'evenodd', clip:[], matrix:[1,0,0,1,0,0] };
  const objects = new Map(), stack = [], defs = [], output = [];
  let currentPath = null, finishedPath = null, records = 0, pointCount = 0, eof = false;
  const mapped = (x,y) => {
    const [a,b,c,d,e,f] = state.matrix;
    const tx=a*x+c*y+e, ty=b*x+d*y+f;
    return state.mode === 1 ? [num(tx),num(ty)] : [num((tx-state.wx)*state.vw/state.ww+state.vx),num((ty-state.wy)*state.vh/state.wh+state.vy)];
  };
  const point = (x,y) => mapped(x,y).join(' ');
  const emit = (d, fill, stroke) => {
    if (!d) invalid('绘图路径为空');
    const scale = state.mode === 1 ? 1 : Math.abs(state.vw/state.ww);
    let svg = `<path d="${d}" fill="${fill ? state.fill : 'none'}" fill-rule="${state.fillRule}" stroke="${stroke ? state.pen : 'none'}" stroke-width="${num(Math.max(1, state.penWidth*scale))}" stroke-linejoin="round"/>`;
    for (const id of state.clip) svg = `<g clip-path="url(#${id})">${svg}</g>`;
    output.push(svg);
  };
  const pathPart = (part, fill=false, stroke=true) => { if(currentPath !== null) currentPath += part; else emit(part,fill,stroke); };
  const select = id => {
    if (id >= 0x80000000) {
      const stock=id-0x80000000;
      if (stock<=5) state.fill=['#ffffff','#c0c0c0','#808080','#404040','#000000','none'][stock];
      else if (stock<=8) { state.pen=['#ffffff','#000000','none'][stock-6]; state.penWidth=1; }
      else invalid(`库存对象 ${stock} 暂未支持`);
    } else {
      const obj=objects.get(id); if(!obj) invalid(`对象 ${id} 缺失`);
      Object.assign(state,obj);
    }
  };
  for(let offset=0;offset<data.length;) {
    if(++records>MAX_RECORDS || offset+8>data.length) invalid('记录数量或边界无效');
    const type=data.readUInt32LE(offset), size=data.readUInt32LE(offset+4);
    if(size<8 || size%4 || offset+size>data.length) invalid('记录长度无效');
    const rec=data.subarray(offset,offset+size);
    const need=(end)=>{if(end>size)invalid(`记录 ${type} 数据截断`);};
    const u=o=>{need(o+4);return rec.readUInt32LE(o);}, i=o=>{need(o+4);return rec.readInt32LE(o);};
    const coords=(start,count,short)=>{
      if((pointCount+=count)>MAX_POINTS)invalid('路径点数超出限制');
      const step=short?4:8;need(start+count*step);
      return Array.from({length:count},(_,n)=>short?[rec.readInt16LE(start+n*step),rec.readInt16LE(start+n*step+2)]:[i(start+n*step),i(start+n*step+4)]);
    };
    switch(type) {
      case 1: if(offset!==0 || size!==headerSize)invalid('文件头位置无效');break;
      case 14: if(offset+size!==data.length)invalid('结束记录位置无效');eof=true;break;
      case 17: state.mode=i(8);if(![1,8].includes(state.mode))invalid(`映射模式 ${state.mode} 暂未支持`);break;
      case 9: state.ww=i(8);state.wh=i(12);if(!state.ww||!state.wh)invalid('窗口尺寸为零');break;
      case 10: state.wx=i(8);state.wy=i(12);break;
      case 11: state.vw=i(8);state.vh=i(12);if(!state.vw||!state.vh)invalid('视口尺寸为零');break;
      case 12: state.vx=i(8);state.vy=i(12);break;
      case 18: case 21: case 22: case 13: break; // Text/raster/brush origin state; those drawing operations have their own gate.
      case 19: if(![1,2].includes(u(8)))invalid('填充规则无效');state.fillRule=u(8)===1?'evenodd':'nonzero';break;
      case 20: if(u(8)!==13)invalid('栅格混合模式暂未支持');break;
      case 33: if(stack.length>=256)invalid("绘图状态层级超出限制");stack.push(structuredClone(state));break;
      case 34: {const n=i(8),index=n<0?stack.length+n:n-1;if(index<0||index>=stack.length)invalid('绘图状态栈无效');state=stack[index];stack.length=index;break;}
      case 35: {need(32);state.matrix=[8,12,16,20,24,28].map(o=>rec.readFloatLE(o));state.matrix.forEach(num);break;}
      case 37: select(u(8));break;
      case 39: {const style=u(12);if(![0,1].includes(style))invalid(`画刷样式 ${style} 暂未支持`);objects.set(u(8),{fill:style===1?'none':color(u(16))});break;}
      case 38: {const style=u(12)&15;if(![0,5].includes(style))invalid('线条样式暂未支持');objects.set(u(8),{pen:style===5?'none':color(u(24)),penWidth:Math.abs(i(16))});break;}
      case 95: {const style=u(28)&15;if(![0,5].includes(style)||u(36)!==0||u(48)!==0)invalid('扩展线条样式暂未支持');objects.set(u(8),{pen:style===5?'none':color(u(40)),penWidth:u(32)});break;}
      case 40: objects.delete(u(8));break;
      case 27: state.x=i(8);state.y=i(12);if(currentPath!==null)currentPath+=`M${point(state.x,state.y)} `;break;
      case 54: {const x=i(8),y=i(12);pathPart(`${currentPath===null?`M${point(state.x,state.y)} `:''}L${point(x,y)} `);state.x=x;state.y=y;break;}
      case 59: currentPath='';finishedPath=null;break;
      case 60: if(currentPath===null)invalid('路径状态无效');finishedPath=currentPath;currentPath=null;break;
      case 61: if(currentPath===null)invalid('路径状态无效');currentPath+='Z ';break;
      case 68: currentPath=null;finishedPath=null;break;
      case 62: case 63: case 64: if(finishedPath===null)invalid('路径状态无效');emit(finishedPath,type!==64,type!==62);finishedPath=null;break;
      case 67: {if(finishedPath===null)invalid('裁剪路径缺失');const mode=u(8);if(![1,5].includes(mode))invalid(`裁剪模式 ${mode} 暂未支持`);if(mode===1&&state.clip.length>=32)invalid("裁剪层级超出限制");const id=`clip${defs.length}`;defs.push(`<clipPath id="${id}" clipPathUnits="userSpaceOnUse"><path d="${finishedPath}" clip-rule="${state.fillRule}"/></clipPath>`);state.clip=mode===5?[id]:[...state.clip,id];finishedPath=null;break;}
      case 75: if(u(8)!==0||u(12)!==5)invalid('区域裁剪暂未支持');state.clip=[];break;
      case 2: case 3: case 4: case 5: case 6: case 85: case 86: case 87: case 88: case 89: {
        const short=type>=85, normalized=short?type-83:type, pts=coords(28,u(24),short);
        const bezier=normalized===2||normalized===5,to=normalized===5||normalized===6,closed=normalized===3;
        if(!pts.length || (bezier && (pts.length-(to?0:1))%3))invalid('曲线路径点数无效');
        let d='',start=0;
        if(!to){d=`M${point(...pts[0])} `;start=1;}
        else if(currentPath===null)d=`M${point(state.x,state.y)} `;
        if(bezier)for(let n=start;n<pts.length;n+=3)d+=`C${point(...pts[n])} ${point(...pts[n+1])} ${point(...pts[n+2])} `;
        else for(let n=start;n<pts.length;n++)d+=`L${point(...pts[n])} `;
        if(closed)d+='Z ';
        pathPart(d,closed,true);if(to)[state.x,state.y]=pts.at(-1);break;
      }
      case 7: case 8: case 90: case 91: {
        const polygons=u(24),total=u(28),short=type>=90;need(32+polygons*4);
        const pts=coords(32+polygons*4,total,short);let start=0,d='';
        for(let p=0;p<polygons;p++){const count=u(32+p*4);if(!count||start+count>total)invalid('多边形点数无效');d+=`M${point(...pts[start])} `;for(let n=1;n<count;n++)d+=`L${point(...pts[start+n])} `;if(type===8||type===91)d+='Z ';start+=count;}
        if(start!==total)invalid('多边形点数无效');pathPart(d,type===8||type===91,true);break;
      }
      case 43: {const x=i(8),y=i(12),r=i(16),b=i(20);pathPart(`M${point(x,y)} L${point(r,y)} L${point(r,b)} L${point(x,b)} Z `,true,true);break;}
      case 70: {const count=u(8);need(12+count);if(count>=4&&u(12)===0x2b464d45)invalid('EMF+ 绘图暂未支持');break;} // Alternate PDF/EPS comments retain the regular EMF fallback records.
      default: invalid(`绘图记录 ${type} 暂未支持`);
    }
    offset+=size;
  }
  if(!eof||records!==declaredRecords||!output.length)invalid('绘图记录不完整');
  const svg=`<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="${left} ${top} ${width} ${height}"><defs>${defs.join('')}</defs>${output.join('')}</svg>`;
  if(svg.length>MAX_BYTES)invalid('转换结果超出限制');
  return Buffer.from(svg);
}
