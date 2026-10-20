// The bundle is evaluated in an isolated QuickJS context. No host callbacks or I/O.
function renderRequest(source, config) {
  try {
    const model = pele.parse(source);
    const measurer = {width(text, size, style) {
      const table = fontMetrics[(style & 1 ? 1 : 0) + (style & 2 ? 2 : 0)];
      let width = 0;
      for (const ch of text) width += table[ch] ?? (/\p{Mark}/u.test(ch) ? 0 : ch.codePointAt(0) >= 0x2e80 ? 1 : .6);
      return width * size;
    }};
    const result = pele.render(model, {
      responsive:false, autoDirection:false, images:false, links:false,
      fontFamily:'Noto Sans', measurer,
    });
    let graph;
    if (model.type === 'flowchart') graph = {type:model.type, nodes:model.nodes, edges:model.edges, subgraphs:model.subgraphs};
    else if (model.type === 'state') graph = {type:model.type, rootDoc:model.rootDoc};
    else if (model.type === 'class') graph = {type:model.type, classes:model.classes, relations:model.relations, notes:model.notes, namespaces:model.namespaces, interfaces:model.interfaces};
    else if (model.type === 'sequence') graph = {type:model.type, actors:model.actors, messages:model.messages};
    else graph = {type:model.type};
    return JSON.stringify({result, graph}, (_, value) => value instanceof Map ? Object.fromEntries(value) : value);
  } catch(error) {
    return JSON.stringify({error:{message:String(error.message),code:error.code || 'runtime',line:error.line || 0,column:error.column || 0}});
  }
}
