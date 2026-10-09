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
    const matches = candidates.filter(el => {
      const domId = el.getAttribute('id') || '';
      // Mermaid 12 prefixes node and subgraph IDs with the containing SVG's ID.
      // Remove that exact prefix before matching; node IDs can contain dashes.
      const prefix = `${svg.id}-`;
      const localId = svg.id && domId.startsWith(prefix) ? domId.slice(prefix.length) : domId;
      return el.getAttribute('data-id') === id || domId === id || localId === id ||
        localId.match(/^flowchart-(.*)-\d+$/)?.[1] === id;
    });
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
  function labelText(el) {
    if (!el) return '';
    // Mermaid's SVG labels have one outer tspan per rendered line.
    const rows = [...el.querySelectorAll('tspan.row')];
    if (rows.length) return rows.map(row => row.textContent).join('\n').trim();
    const copy = el.cloneNode(true);
    copy.querySelectorAll('br').forEach(br => br.replaceWith('\n'));
    return copy.textContent.trim();
  }
  function outlinesFor(el, dim) {
    const outlines = [];
    for (const glyph of el.querySelectorAll('path, rect, polygon, polyline, circle, ellipse, line')) {
      if (glyph.closest('.label, .nodeLabel, .cluster-label, defs')) continue;
      const cs = getComputedStyle(glyph);
      if (cs.display === 'none' || cs.visibility === 'hidden' || +cs.opacity === 0) continue;
      const fill = cssColor(cs.fill, null), stroke = cssColor(cs.stroke, null);
      if (!fill && !stroke) continue;
      const transform = glyph.getCTM();
      // Keep disjoint SVG subpaths separate; joining them creates spurious lines.
      const paths = glyph.tagName.toLowerCase() === 'path' ?
        (glyph.getAttribute('d') || '').match(/[Mm][^Mm]*/g) || [] : [null];
      for (const d of paths) {
        const part = d === null ? glyph : glyph.cloneNode(false);
        if (d !== null) part.setAttribute('d', d);
        const length = part.getTotalLength();
        if (!(length > 0) || !transform) continue;
        const count = Math.min(600, Math.max(8, Math.ceil(length / 3)));
        const points = Array.from({length:count+1}, (_, i) => {
          const p = part.getPointAtLength(length*i/count);
          return {x:(transform.a*p.x+transform.c*p.y+transform.e-dim.x)/dim.width,
                  y:1-(transform.b*p.x+transform.d*p.y+transform.f-dim.y)/dim.height};
        });
        const closed = d !== null ? /[zZ]\s*$/.test(d) :
          !['line','polyline'].includes(glyph.tagName.toLowerCase());
        outlines.push({points, closed, fill:Boolean(fill), stroke:Boolean(stroke)});
      }
    }
    return outlines;
  }
  function pathSegments(path) {
    const tokens = (path.getAttribute('d') || '').match(/[a-zA-Z]|[-+]?(?:\d*\.\d+|\d+\.?\d*)(?:[eE][-+]?\d+)?/g) || [];
    const counts = {M:2,L:2,H:1,V:1,Q:4,C:6,S:4,T:2};
    const t = path.getCTM(), segments = [];
    let i=0, command, x=0, y=0, previous, control;
    while (i < tokens.length) {
      if (/^[a-z]$/i.test(tokens[i])) command = tokens[i++];
      const type = command?.toUpperCase(), count = counts[type];
      if (!count || i+count > tokens.length) return null;
      const values = tokens.slice(i,i+count).map(Number);
      if (!values.every(Number.isFinite)) return null;
      i += count;
      const relative = command !== type;
      const point = (a,b) => ({x:a+(relative?x:0),y:b+(relative?y:0)});
      let points, outputType = type;
      if (type === 'H') {points=[{x:values[0]+(relative?x:0),y}];outputType='L';}
      else if (type === 'V') {points=[{x,y:values[0]+(relative?y:0)}];outputType='L';}
      else {
        points=[];
        for(let j=0;j<count;j+=2) points.push(point(values[j],values[j+1]));
        if (type === 'S' || type === 'T') {
          const reflect = control && (type === 'S' ? ['C','S'] : ['Q','T']).includes(previous) ?
            {x:2*x-control.x,y:2*y-control.y} : {x,y};
          points.unshift(reflect);outputType=type==='S'?'C':'Q';
        }
      }
      control = ['C','Q'].includes(outputType) ? points[points.length-2] : null;
      ({x,y}=points[points.length-1]); previous=type;
      segments.push({type:outputType,points:points.map(p=>({x:t.a*p.x+t.c*p.y+t.e,y:t.b*p.x+t.d*p.y+t.f}))});
      if(type==='M') command=relative?'l':'L';
    }
    return segments;
  }
  const nodes = data.nodes.map(n => {
    const id = String(n.id), el = elementFor(id);
    if (!el) throw new Error(`Cannot locate SVG element for Mermaid node '${id}'`);
    const dim = geometry(el);
    if (!(dim.width > 0 && dim.height > 0)) throw new Error(`Invalid bounds for Mermaid node '${id}'`);
    const container = el.querySelector('.basic, .label-container');
    // Some shapes (notably stadiums) wrap their painted paths in a <g>.
    const glyph = container?.matches('rect, polygon, ellipse, circle, path') ? container :
      container?.querySelector('path, rect, polygon, ellipse, circle') ||
      el.querySelector('rect, polygon, ellipse, circle, path');
    const cs = getComputedStyle(glyph || el);
    const textEl = el.querySelector('text, foreignObject');
    const fontCss = textEl ? getComputedStyle(textEl) : cs;
    const labelEl = el.querySelector('.cluster-label, .nodeLabel, .label, text');
    // Some symbols deliberately suppress their label (e.g. hourglass).
    const label = labelEl ? labelText(labelEl) : formatLabel(n.label, id);
    const outlines = outlinesFor(el, dim);
    const connection_points = {};
    for (const side of ['right','top','left','bottom']) {
      const horizontal = side === 'right' || side === 'left';
      const hits = [];
      for (const outline of outlines) {
        const pts = outline.closed || outline.fill ? [...outline.points, outline.points[0]] : outline.points;
        for (let i=1;i<pts.length;i++) {
          const a = pts[i-1], b = pts[i];
          const av = horizontal ? a.y : a.x, bv = horizontal ? b.y : b.x;
          if ((av <= .5 && bv >= .5 || bv <= .5 && av >= .5) && av !== bv) {
            const t = (.5-av)/(bv-av);
            hits.push(horizontal ? a.x+t*(b.x-a.x) : a.y+t*(b.y-a.y));
          }
        }
      }
      if (hits.length) {
        const value = side === 'right' || side === 'top' ? Math.max(...hits) : Math.min(...hits);
        connection_points[side] = horizontal ? [value,.5] : [.5,value];
      }
    }
    return {
      id, ...dim, text:label, shape: String(n.shape || n.type || ''),
      corner_radius: glyph?.tagName.toLowerCase() === 'rect' ? glyph.rx.baseVal.value : 0,
      fill: cssColor(cs.fill, '#E5EFFA'),
      stroke: cssColor(cs.stroke, '#4472C4'),
      font_color: cssColor(fontCss.fill, '#172D4A'),
      font_size: Number.parseFloat(fontCss.fontSize) || 14,
      is_group: Boolean(n.isGroup),
      label_bounds: labelEl ? geometry(labelEl) : null,
      outlines, connection_points
    };
  });
  const edges = (data.edges || []).map(e => {
    const source = String(e.start ?? e.source ?? ''), target = String(e.end ?? e.target ?? '');
    const edgePath = [...svg.querySelectorAll('path.flowchart-link')].find(path =>
      path.id === e.id || path.id === `${svg.id}-${e.id}`);
    const edgeLabel = [...svg.querySelectorAll('.edgeLabel .label')].find(label =>
      label.getAttribute('data-id') === e.id);
    const labelBackground = edgeLabel?.querySelector('rect.background');
    const labelTextEl = edgeLabel?.querySelector('text');
    let route, segments;
    if (edgePath) {
      const length = edgePath.getTotalLength(), t = edgePath.getCTM();
      const count = Math.min(100, Math.max(2, Math.ceil(length/8)));
      route = Array.from({length:count+1}, (_, i) => {
        const p = edgePath.getPointAtLength(length*i/count);
        return {x:t.a*p.x+t.c*p.y+t.e,y:t.b*p.x+t.d*p.y+t.f};
      });
      segments = pathSegments(edgePath);
      // Mermaid shortens the centerline for its SVG marker; native Visio
      // arrowheads end at the glued point, so restore the marker's tip.
      const marker = getComputedStyle(edgePath).markerEnd;
      const markerId = marker.match(/#([^)'" ]+)/)?.[1];
      const markerEl = markerId ? document.getElementById(markerId) : null;
      if (markerEl && markerId.includes('pointEnd')) {
        const vb = markerEl.viewBox.baseVal;
        const gap = (vb.width-markerEl.refX.baseVal.value)*markerEl.markerWidth.baseVal.value/vb.width;
        const a=route[route.length-2], b=route[route.length-1], length=Math.hypot(b.x-a.x,b.y-a.y);
        const dx=(b.x-a.x)/length*gap, dy=(b.y-a.y)/length*gap;
        route[route.length-1]={x:b.x+dx,y:b.y+dy};
        if(segments?.length) {
          const last=segments[segments.length-1];
          last.points[last.points.length-1]=route[route.length-1];
        }
      }
    }
    return {
      source, target, text:labelText(edgeLabel) || formatLabel(e.label, ''), route, segments,
      label_bounds: edgeLabel ? geometry(edgeLabel) : null,
      label_background: labelBackground ? cssColor(getComputedStyle(labelBackground).fill, null) : '#FFFFFF',
      font_color: labelTextEl ? cssColor(getComputedStyle(labelTextEl).fill, '#172D4A') : '#172D4A',
      // Mermaid getData supplies arrowTypeEnd or arrowTypeStart for actual directedness.
      // 'arrow_open' is an undirected line in older diagram models.
      arrow: e.arrowTypeEnd !== undefined ? e.arrowTypeEnd !== 'none' : e.type !== 'arrow_open',
      start_arrow: e.arrowTypeStart !== undefined && e.arrowTypeStart !== 'none',
      dash: e.pattern === 'dotted' || e.pattern === 'dashed',
      stroke: edgePath ? cssColor(getComputedStyle(edgePath).stroke, '#4472C4') : '#4472C4'
    };
  });
  return {nodes,edges};
})()
