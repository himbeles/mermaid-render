/* SVG DOM -> serializable display list. Port of mermaid-to-visio/svgCapture.ts
 * Executes in a real browser where getBBox/getCTM/getComputedStyle work.
 */
(() => {
  const SKIP = new Set(['defs','marker','clippath','symbol','pattern','mask']);
  const f = (n, fallback=0) => Number.isFinite(parseFloat(n)) ? parseFloat(n) : fallback;
  const num = (el, key) => f(el.getAttribute(key));
  function color(s) {
    if (!s || s === 'none' || s === 'transparent') return null;
    if (s.startsWith('#')) {
      if (s.length === 4) return '#' + [...s.slice(1)].map(x=>x+x).join('').toUpperCase();
      return s.toUpperCase();
    }
    const match = s.match(/^rgba?\(\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)(?:[,\s/]+([\d.]+))?\s*\)/);
    if (match) {
      if (match[4] !== undefined && Number(match[4]) === 0) return null;
      return '#' + match.slice(1,4).map(x => Math.max(0,Math.min(255, Math.round(Number(x)))).toString(16).padStart(2,'0')).join('').toUpperCase();
    }
    return s; // Visio may not accept named colors; browser normally resolves to rgb
  }
  const pt = (x,y) => ({x,y});
  function xyToRoot(el, x, y) {
    const m = el.getCTM();
    return m ? pt(m.a*x+m.c*y+m.e, m.b*x+m.d*y+m.f) : pt(x,y);
  }
  function simplify(points, tolerance=0.35) {
    if (points.length<=2) return points;
    const out=[points[0]];
    for (let i=1;i<points.length-1;i++) {
      const a=out[out.length-1], b=points[i], c=points[i+1];
      const dx=c.x-a.x, dy=c.y-a.y, length=Math.hypot(dx,dy)||1;
      if (Math.abs((b.x-a.x)*dy-(b.y-a.y)*dx)/length>tolerance) out.push(b);
    }
    out.push(points[points.length-1]);
    return out;
  }
  function ellipse(cx,cy,rx,ry) {
    return Array.from({length:48},(_,i)=>{
      const a=i/48*2*Math.PI;
      return pt(cx+rx*Math.cos(a),cy+ry*Math.sin(a));
    });
  }
  function pathPoints(el) {
    let total;
    try { total=el.getTotalLength(); } catch { return null; }
    if (!(total>0) || !Number.isFinite(total)) return null;
    const step=Math.max(1.5,total/600), pts=[];
    for (let t=0;t<total;t+=step) {
      const p=el.getPointAtLength(t); pts.push(pt(p.x,p.y));
    }
    const end=el.getPointAtLength(total);
    pts.push(pt(end.x,end.y));
    return pts;
  }
  function hidden(el) {
    const s=getComputedStyle(el);
    return s.display==='none'||s.visibility==='hidden'||f(s.opacity,1)===0;
  }
  function poly(el) {
    const name=el.tagName.toLowerCase();
    let local=null, closed=false;
    if (name==='rect') {
      const x=num(el,'x'), y=num(el,'y'), w=num(el,'width'), h=num(el,'height');
      if(w<=0||h<=0) return null;
      local=[pt(x,y),pt(x+w,y),pt(x+w,y+h),pt(x,y+h)];closed=true;
    } else if(name==='circle') {
      const r=num(el,'r');if(r<=0)return null;
      local=ellipse(num(el,'cx'),num(el,'cy'),r,r);closed=true;
    } else if(name==='ellipse') {
      const rx=num(el,'rx'),ry=num(el,'ry');if(rx<=0||ry<=0)return null;
      local=ellipse(num(el,'cx'),num(el,'cy'),rx,ry);closed=true;
    } else if(name==='line') {
      local=[pt(num(el,'x1'),num(el,'y1')),pt(num(el,'x2'),num(el,'y2'))];
    } else if(name==='polyline'||name==='polygon') {
      const raw=el.getAttribute('points')||'';
      const nums=raw.trim().split(/[\s,]+/).map(Number).filter(Number.isFinite);
      local=[];for(let i=0;i+1<nums.length;i+=2)local.push(pt(nums[i],nums[i+1]));
      closed=name==='polygon';
    } else if(name==='path') {
      local=pathPoints(el);closed=/z\s*$/i.test(el.getAttribute('d')||'');
    }
    if(!local||local.length<2)return null;
    const s=getComputedStyle(el), fill=color(s.fill), stroke=color(s.stroke);
    if(!fill&&!stroke)return null;
    const points=simplify(local.map(p=>xyToRoot(el,p.x,p.y)));
    if(points.length<2)return null;
    return {kind:'poly',points,closed,fill,stroke,strokeWidthPx:f(s.strokeWidth,1),
      dash: !!s.strokeDasharray && s.strokeDasharray!=='none'&&s.strokeDasharray!=='0',
      beginArrow: !!s.markerStart && s.markerStart !== 'none',
      endArrow: !!s.markerEnd && s.markerEnd !== 'none'};
  }
  function textItem(el, value) {
    value=value.replace(/\s+/g,' ').trim();if(!value)return null;
    let bbox;
    try {bbox=el.getBBox();}catch{return null;}
    if(bbox.width===0&&bbox.height===0)return null;
    const corners=[xyToRoot(el,bbox.x,bbox.y),xyToRoot(el,bbox.x+bbox.width,bbox.y),
      xyToRoot(el,bbox.x+bbox.width,bbox.y+bbox.height),xyToRoot(el,bbox.x,bbox.y+bbox.height)];
    const xs=corners.map(p=>p.x), ys=corners.map(p=>p.y);
    const s=getComputedStyle(el);
    let leaf=el;
    while(true) {
      const inner=[...leaf.children].find(c=>c.tagName.toLowerCase()==='tspan');
      if(!inner)break;leaf=inner;
    }
    const ls=getComputedStyle(leaf);
    const weight=ls.fontWeight||s.fontWeight||'400';
    return {kind:'text',text:value,x:Math.min(...xs),y:Math.min(...ys),
      width:Math.max(...xs)-Math.min(...xs),height:Math.max(...ys)-Math.min(...ys),
      fontPx:f(s.fontSize,12),fontFamily:(s.fontFamily||'Arial').split(',')[0].replace(/["']/g,'').trim(),
      bold:weight==='bold'||parseInt(weight,10)>=600,italic:(ls.fontStyle||s.fontStyle)==='italic',
      anchor:['middle','end'].includes(s.textAnchor)?s.textAnchor:'start',fill:color(ls.fill)||color(s.fill)||'#000000'};
  }
  function capture(svg) {
    const vb=(svg.getAttribute('viewBox')||'').trim().split(/[\s,]+/).map(Number);
    const b=vb.length===4 && vb.every(Number.isFinite) ? {width:vb[2],height:vb[3]} : svg.getBBox();
    svg.setAttribute('width',String(b.width));svg.setAttribute('height',String(b.height));
    Object.assign(svg.style,{width:`${b.width}px`,height:`${b.height}px`,maxWidth:'none'});
    const items=[];
    // Stable DOM references associate artwork with semantic diagram objects.
    const elementIds=new Map([...svg.querySelectorAll('*')].map((el,i)=>[el,i]));
    function add(item, el) { if(item) items.push({...item,element:elementIds.get(el)}); }
    function walk(el) {
      const name=el.tagName.toLowerCase();
      if(SKIP.has(name) || (el instanceof SVGGraphicsElement && hidden(el)))return;
      if(name==='text') {
        const lines=[...el.children].filter(c=>c.tagName.toLowerCase()==='tspan'&&c.hasAttribute('x'));
        if(lines.length>=2) {
          for(const l of lines){add(textItem(l,l.textContent||''),el);}
        } else {
          add(textItem(el,el.textContent||''),el);
        }
        return;
      }
      add(poly(el),el);
      for(const child of el.children)walk(child);
    }
    for(const child of svg.children)walk(child);
    return {width:b.width,height:b.height,items};
  }
  return capture(document.querySelector('svg'));
})()
