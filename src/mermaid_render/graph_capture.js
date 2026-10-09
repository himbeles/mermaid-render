/* Recover graph structure from Mermaid's own flowchart DB and geometry from SVG.
 * Evaluated in Chromium after mermaid.render() has inserted an SVG in #mount.
 * A missing node mapping is an error: never silently return disconnected shapes.
 */
(async () => {
  const m = window.__mermaid;
  const source = window.__mermaidSource;
  const diagram = await m.mermaidAPI.getDiagramFromText(source);
  if (!/^flowchart/.test(diagram.type)) {
    throw new Error(`Connected VSDX export supports Mermaid flowcharts, not ${diagram.type}`);
  }
  const db = diagram.db;
  const data = typeof db.getData === 'function' ? db.getData() : {
    nodes: [...db.getVertices().values()],
    edges: db.getEdges().map(e => ({start:e.start,end:e.end,label:e.text,type:e.type}))
  };
  if (!data.nodes?.length) throw new Error('Mermaid flowchart has no nodes');
  const svg = document.querySelector('#mount svg');
  if (!svg) throw new Error('Mermaid did not render an SVG');
  const vb = (svg.getAttribute('viewBox') || '').trim().split(/[\s,]+/).map(Number);
  if (vb.length === 4 && vb.every(Number.isFinite)) {
    svg.setAttribute('width', String(vb[2]));
    svg.setAttribute('height', String(vb[3]));
    Object.assign(svg.style, {width:`${vb[2]}px`,height:`${vb[3]}px`,maxWidth:'none'});
  }
  const geometry = (el) => {
    const b = el.getBBox(), t = el.getCTM();
    if (!t) throw new Error('Could not measure SVG node');
    const corners = [[b.x,b.y],[b.x+b.width,b.y],[b.x+b.width,b.y+b.height],[b.x,b.y+b.height]];
    const pts = corners.map(([x,y]) => ({x:t.a*x+t.c*y+t.e,y:t.b*x+t.d*y+t.f}));
    const xs = pts.map(p=>p.x), ys=pts.map(p=>p.y);
    return {x:Math.min(...xs),y:Math.min(...ys),width:Math.max(...xs)-Math.min(...xs),height:Math.max(...ys)-Math.min(...ys)};
  };
  const candidates = [...svg.querySelectorAll('g.node, g.cluster, [data-id]')].filter(el => el instanceof SVGGraphicsElement);
  function elementFor(id) {
    const matches = candidates.filter(el =>
      el.getAttribute('data-id') === id ||
      el.getAttribute('id') === id ||
      // Older Mermaid uses flowchart-ID-0; node IDs can include dashes.
      (el.getAttribute('id') || '').match(/^flowchart-(.*)-\d+$/)?.[1] === id);
    return matches.find(el => el.classList.contains('node')) ||
      matches.find(el => el.classList.contains('cluster')) || matches[0];
  }
  function formatLabel(x, fallback) {
    if (typeof x === 'string') return x;
    if (typeof x === 'number') return String(x);
    if (x && typeof x === 'object' && typeof x.text === 'string') return x.text;
    return fallback;
  }
  const cssColor = (value, fallback) => {
    if (!value || value === 'none' || value === 'transparent') return fallback;
    if (value.startsWith('#')) return value;
    const parts = value.match(/^rgba?\(\s*(\d+)[,\s]+(\d+)[,\s]+(\d+)/);
    if (parts) return '#' + parts.slice(1,4).map(n => (+n).toString(16).padStart(2,'0')).join('').toUpperCase();
    return fallback;
  };
  const nodes = data.nodes.map(n => {
    const id = String(n.id), el = elementFor(id);
    if (!el) throw new Error(`Cannot locate SVG element for Mermaid node '${id}'`);
    const dim = geometry(el);
    if (!(dim.width > 0 && dim.height > 0)) throw new Error(`Invalid bounds for Mermaid node '${id}'`);
    const glyph = el.querySelector('.basic, .label-container, rect, polygon, ellipse, circle, path');
    const cs = getComputedStyle(glyph || el);
    const textEl = el.querySelector('text, foreignObject');
    const fontCss = textEl ? getComputedStyle(textEl) : cs;
    const label = (el.querySelector('.nodeLabel, .label, text')?.textContent || '').trim() ||
      formatLabel(n.label, id);
    return {
      id, ...dim, text:label, shape: String(n.shape || ''),
      fill: cssColor(cs.fill, '#E5EFFA'),
      stroke: cssColor(cs.stroke, '#4472C4'),
      font_color: cssColor(fontCss.fill, '#172D4A'),
      font_size: Number.parseFloat(fontCss.fontSize) || 14,
      is_group: Boolean(n.isGroup)
    };
  });
  const edges = (data.edges || []).map(e => {
    const source = String(e.start ?? e.source ?? ''), target = String(e.end ?? e.target ?? '');
    return {
      source, target, text:formatLabel(e.label, ''),
      // Mermaid getData supplies arrowTypeEnd or arrowTypeStart for actual directedness.
      // 'arrow_open' is an undirected line in older diagram models.
      arrow: e.arrowTypeEnd !== undefined ? e.arrowTypeEnd !== 'none' : e.type !== 'arrow_open',
      start_arrow: e.arrowTypeStart !== undefined && e.arrowTypeStart !== 'none',
      dash: e.pattern === 'dotted' || e.pattern === 'dashed',
      stroke: '#4472C4'
    };
  });
  return {nodes,edges};
})()
