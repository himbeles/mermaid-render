/* Join sequence identities to captured SVG artwork; never flatten messages. */
async (display) => {
  const diagram=await window.__mermaid.mermaidAPI.getDiagramFromText(window.__mermaidSource);
  const svg=document.querySelector('#mount svg'),elements=[...svg.querySelectorAll('*')];
  const participants=[...diagram.db.getActors().keys()].map(id=>({id,items:[]}));
  const byId=new Map(participants.map(p=>[p.id,p]));
  const centers=new Map([...svg.querySelectorAll('[data-et="life-line"]')].map(el=>[el.getAttribute('data-id'),+el.getAttribute('x1')]));
  const messages=[...svg.querySelectorAll('[data-et="message"]')],messageElements=new Set(messages);
  const labels=new Map(),numbers=new Map();
  for(const message of messages) {
    const texts=[];
    for(let el=message.previousElementSibling;el?.matches('text.messageText');el=el.previousElementSibling) texts.unshift(el);
    for(const el of texts) labels.set(el,message);
    for(let el=message.nextElementSibling;el&&!el.matches('text.messageText, [data-et="message"], g, rect');el=el.nextElementSibling)
      if(el.matches('text.sequenceNumber')) numbers.set(el,message);
  }
  const groups=new Map(),messageItems=new Map(messages.map(el=>[el,{labels:[],numbers:[]}]));
  function participantFor(el) {
    const identity=el.closest('[data-et="life-line"], [data-et="participant"]');
    if(identity) return identity.getAttribute('data-id');
    const bottom=el.closest('.actor-bottom')||(el.parentElement?.matches('g')?el.parentElement.querySelector('.actor-bottom'):null);
    if(bottom) return bottom.getAttribute('name');
    if(/^activation\d+$/.test(el.getAttribute('class')||'')) {
      const x=+el.getAttribute('x')+(+el.getAttribute('width'))/2;
      return [...centers].sort((a,b)=>Math.abs(a[1]-x)-Math.abs(b[1]-x))[0]?.[0];
    }
    return null;
  }
  for(const item of display.items) {
    const el=elements[item.element];
    if(!el) throw Error('Sequence capture lost an SVG element');
    if(messageElements.has(el)) continue;
    if(labels.has(el)) {messageItems.get(labels.get(el)).labels.push(item);continue;}
    if(numbers.has(el)) {messageItems.get(numbers.get(el)).numbers.push(item);continue;}
    if(el.matches('line')&&el.getAttribute('x1')===el.getAttribute('x2')&&el.getAttribute('y1')===el.getAttribute('y2')) continue;
    const actor=participantFor(el);
    if(actor) {
      if(!byId.has(actor)) throw Error(`Unknown sequence participant ${actor}`);
      // Mermaid sometimes leaves a 2000px lifeline below its SVG viewport
      // when mirrored actors are disabled. Export only the visible portion.
      if(el.matches('[data-et="life-line"]'))
        item.points=item.points.map(p=>({...p,y:Math.max(0,Math.min(display.height,p.y))}));
      byId.get(actor).items.push(item);continue;
    }
    const container=el.closest('[data-et="note"], [data-et="control-structure"]')||el.closest('g');
    const key=container||el;
    if(!groups.has(key)) groups.set(key,{kind:container?.getAttribute('data-et')||'decoration',items:[]});
    groups.get(key).items.push(item);
  }
  const bounds=items=>{
    const points=items.flatMap(i=>i.kind==='poly'?i.points:[{x:i.x,y:i.y},{x:i.x+i.width,y:i.y+i.height}]);
    const xs=points.map(p=>p.x),ys=points.map(p=>p.y);
    return {x:Math.min(...xs),y:Math.min(...ys),width:Math.max(...xs)-Math.min(...xs),height:Math.max(...ys)-Math.min(...ys)};
  };
  for(const p of participants) {
    if(!p.items.length) throw Error(`Could not capture sequence participant ${p.id}`);
    Object.assign(p,bounds(p.items));
  }
  const color=value=>{const m=value.match(/rgba?\((\d+)[,\s]+(\d+)[,\s]+(\d+)/);return m?'#'+m.slice(1).map(n=>(+n).toString(16).padStart(2,'0')).join(''):value;};
  const edges=messages.map(el=>{
    const source=el.getAttribute('data-from'),target=el.getAttribute('data-to');
    if(!byId.has(source)||!byId.has(target)) throw Error('Sequence message has no participant mapping');
    const cs=getComputedStyle(el),length=el.getTotalLength(),t=el.getCTM();
    const root=p=>({x:t.a*p.x+t.c*p.y+t.e,y:t.b*p.x+t.d*p.y+t.f});
    const start=root(el.getPointAtLength(0)),end=root(el.getPointAtLength(length));
    let route=[start,end];
    if(source===target) {
      const extent=Math.max(...Array.from({length:21},(_,i)=>root(el.getPointAtLength(length*i/20)).x));
      route=[start,{x:extent,y:start.y},{x:extent,y:end.y},end];
    }
    const {labels,numbers}=messageItems.get(el),marker=cs.markerEnd;
    return {source,target,route,preserve_route:true,text:labels.map(i=>i.text).join('\n'),
      label_bounds:labels.length?bounds(labels):null,label_background:null,
      font_color:labels[0]?.fill||'#000000',font_size:labels[0]?.fontPx||16,stroke:color(cs.stroke),stroke_width:parseFloat(cs.strokeWidth),
      dash:cs.strokeDasharray!=='none'&&cs.strokeDasharray!=='0',
      arrow:marker!=='none'&&!marker.includes('crosshead'),start_arrow:cs.markerStart!=='none',
      cross:marker.includes('crosshead'),open:marker.includes('filled-head')||marker.includes('stick'),numbers};
  });
  return {participants,edges,decorations:[...groups.values()],width:display.width,height:display.height};
}
