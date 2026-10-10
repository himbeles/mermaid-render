"""Native sequence participants, grouped lifelines, and glued 1D messages."""
from __future__ import annotations

from io import BytesIO
from math import cos, pi, sin
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile

from .semantic import _cell, _connector, _PORTS
from .vsdx import CoordinateSpace, PX_TO_IN, _parts, _shape_geometry, _shape_text, number, tag, xml_bytes


def _bounds(items):
    points = []
    for item in items:
        if item['kind'] == 'poly':
            points.extend((p['x'], p['y']) for p in item['points'])
        else:
            points.extend([(item['x'], item['y']), (item['x']+item['width'], item['y']+item['height'])])
    return min(x for x, _ in points), min(y for _, y in points), max(x for x, _ in points), max(y for _, y in points)


class _LocalSpace:
    def __init__(self, space, left, bottom):
        self.space, self.left, self.bottom = space, left, bottom

    def point(self, x, y):
        px, py = self.space.point(x, y)
        return px-self.left, py-self.bottom


def build_sequence_vsdx(graph, *, title='Sequence Diagram'):
    """Group participant artwork so messages follow a moved participant column.

    Frames and notes are independent editable groups. Message endpoint ports
    are on the participant group, preserving activation offsets and chronology.
    """
    participants = [dict(p, extra_ports=[]) for p in graph['participants']]
    if not participants:
        raise ValueError('Connected sequence VSDX requires participants')
    edges = [dict(e) for e in graph['edges']]
    nodes = {p['id']: p for p in participants}
    for edge in edges:
        for side, point in [('source', edge['route'][0]), ('target', edge['route'][-1])]:
            node = nodes[edge[side]]
            ports = node['extra_ports']
            edge[side+'_port'] = 4+len(ports)
            ports.append(((point['x']-node['x'])/node['width'], 1-(point['y']-node['y'])/node['height']))
    all_items = [i for p in participants for i in p['items']]
    all_items += [i for d in graph['decorations'] for i in d['items']]
    x0, y0, x1, y1 = _bounds(all_items)
    points = [(x0,y0),(x1,y1)] + [(p['x'],p['y']) for e in edges for p in e['route']]
    for edge in edges:
        for bounds in [edge.get('label_bounds'), *edge.get('numbers', [])]:
            if bounds:
                points.extend([(bounds['x'],bounds['y']),
                               (bounds['x']+bounds['width'],bounds['y']+bounds['height'])])
    space = CoordinateSpace(points)
    page = ET.Element(tag('PageContents'), {'{http://www.w3.org/XML/1998/namespace}space':'preserve'})
    shapes = ET.SubElement(page, tag('Shapes'))
    connects = ET.Element(tag('Connects'))
    next_id = 1

    def group(items, name, ports=None):
        nonlocal next_id
        left, top, right, bottom = _bounds(items)
        width, height = max((right-left)*PX_TO_IN, .001), max((bottom-top)*PX_TO_IN,.001)
        px, py = space.point(left,bottom)
        group_id = next_id
        next_id += 1
        unique_name=name if ports is not None else f'{name}.{group_id}'
        shape = ET.SubElement(shapes,tag('Shape'),{'ID':str(group_id),'NameU':unique_name,'Type':'Group'})
        for key, value in [('PinX',px+width/2),('PinY',py+height/2),('Width',width),('Height',height),
                           ('LocPinX',width/2),('LocPinY',height/2),('Angle',0),('SelectMode',0),('ObjType',1)]:
            _cell(shape,key,value)
        if ports is not None:
            connection = ET.SubElement(shape,tag('Section'),{'N':'Connection'})
            for ix,(fx,fy) in enumerate([(x,y) for _,x,y in _PORTS.values()]+ports):
                row = ET.SubElement(connection,tag('Row'),{'T':'Connection','IX':str(ix)})
                _cell(row,'X',width*fx,f'Width*{number(fx)}')
                _cell(row,'Y',height*fy,f'Height*{number(fy)}')
                for key,value in [('DirX',0),('DirY',0),('Type',0),('AutoGen',0),('Prompt','')]:
                    _cell(row,key,value)
        children = ET.SubElement(shape,tag('Shapes'))
        local = _LocalSpace(space,px,py)
        for item in items:
            child=ET.SubElement(children,tag('Shape'),{'ID':str(next_id),'Type':'Shape','NameU':f'{name}.Part{next_id}'})
            next_id+=1
            if item['kind']=='poly':
                _shape_geometry(child,item,local)
            else:
                # A tight browser glyph box can wrap in another viewer's
                # substitute font. Keep its center but allow extra width.
                padding=max(4,item['width']*.12)
                text=dict(item,x=item['x']-padding,width=item['width']+2*padding,anchor='middle')
                if name=='Sequence.control-structure':
                    text['y']+=3  # Keep frame captions clear of their border.
                _shape_text(child,text,local)
                for key in ['LeftMargin','RightMargin','TopMargin','BottomMargin']:
                    _cell(child,key,0)
        return group_id

    # Background areas stay behind lifelines; frame tabs and notes cover them.
    for decoration in graph['decorations']:
        if decoration['kind'] not in ('note', 'control-structure'):
            group(decoration['items'],f'Sequence.{decoration["kind"]}')
    ids = {p['id']:group(p['items'],f'Participant.{p["id"]}',p['extra_ports']) for p in participants}
    for decoration in graph['decorations']:
        if decoration['kind']=='control-structure':
            group(decoration['items'],'Sequence.control-structure')
    for decoration in graph['decorations']:
        if decoration['kind']=='note':
            group(decoration['items'],'Sequence.Note')
    for edge in edges:
        connector_id=next_id
        _connector(shapes,connects,connector_id,edge,ids,nodes,space,'mermaid')
        shape=shapes[-1]
        next_id+=1
        _cell(shape,'ShapeRouteStyle',1 if edge['source']==edge['target'] else 2)
        _cell(shape,'ConFixedCode',2)  # Preserve message chronology on reroute.
        if edge.get('open'):
            shape.find("./"+tag('Cell')+"[@N='EndArrow']").set('V','1')
        if edge.get('cross'):
            # Cross heads stay attached to the message's end as it moves.
            width=float(shape.find("./"+tag('Cell')+"[@N='Width']").get('V'))
            geo=ET.SubElement(shape,tag('Section'),{'N':'Geometry','IX':'1'})
            _cell(geo,'NoFill',1)
            for ix,(dx,dy) in enumerate([(-3,-3),(3,3),(-3,3),(3,-3)],1):
                row=ET.SubElement(geo,tag('Row'),{'IX':str(ix),'T':'MoveTo' if ix in [1,3] else 'LineTo'})
                _cell(row,'X',width+dx*PX_TO_IN,f'Width+{number(dx*PX_TO_IN)}')
                _cell(row,'Y',dy*PX_TO_IN)
        if edge.get('numbers'):
            items=[]
            for label in edge['numbers']:
                cx=label['x']+label['width']/2
                cy=label['y']+label['height']/2
                radius=max(label['width'],label['height'])/2+3
                items.append({'kind':'poly','closed':True,'fill':edge['stroke'],'stroke':None,
                              'points':[{'x':cx+radius*cos(i*pi/24),'y':cy+radius*sin(i*pi/24)} for i in range(48)]})
                items.append(label)
            group(items,'Sequence.Number')
            number_shape=shapes[-1]
            bx,by=space.point(edge['route'][0]['x'],edge['route'][0]['y'])
            for key,coordinate in [('PinX','BeginX'),('PinY','BeginY')]:
                c=number_shape.find('./'+tag('Cell')+f"[@N='{key}']")
                offset=float(c.get('V'))-(bx if key=='PinX' else by)
                c.set('F',f'Sheet.{connector_id}!{coordinate}+{number(offset)}')
    if len(connects): page.append(connects)
    output=BytesIO()
    with ZipFile(output,'w',compression=ZIP_DEFLATED) as archive:
        for name,data in _parts(xml_bytes(page),space.page_width,space.page_height,title).items():
            archive.writestr(name,data)
    return output.getvalue()
