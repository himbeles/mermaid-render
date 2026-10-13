"""Class compartments, UML markers, and connected multiplicities survive export."""
from io import BytesIO
from pathlib import Path
from math import isfinite
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pytest
from mermaid_render import api
from mermaid_render.vsdx import NS_MAIN

NS = {'v': NS_MAIN}
SOURCES = {
    'members': '''classDiagram
class Animal {
    <<abstract>>
    +String name
    -int age
    #bool active
    ~String tag
    +eat(food)$ bool
    +move()* void
}
class Duck {
    +swim()
}
Animal <|-- Duck : inherits
note for Animal "Base type"
''',
    'relationships': '''classDiagram
direction LR
Parent <|-- Child : inheritance
Contract <|.. Service : realization
Whole *-- Part : composition
Team o-- Person : aggregation
Client --> Server : association
Caller ..> Target : dependency
A -- B : link
C .. D : dashed
Provider ()-- Consumer : provides
One <|--|> Two : mutual inheritance
Left *--* Right : double composition
EndPart --* EndWhole : reverse composition
''',
    'multiplicities': '''classDiagram
direction LR
Order "1" *-- "1..*" Item : contains
Customer "1" --> "0..*" Order : places
Account "owner" -- "accounts" Customer
Order "related" --> "previous" Order : revises
''',
    'namespaces': '''classDiagram
namespace App {
    namespace Domain {
        class Model {
            +String id
            +validate() bool
        }
        class Repository {
            <<interface>>
            +get(id) Model
        }
    }
    class Controller
}
namespace Infrastructure {
    class Storage
}
Repository <|.. Storage : implements
Controller --> Repository : uses
Repository --> Model : loads
''',
    'generics': '''classDiagram
class Box~T~ {
    +T value
    +get() T
}
class Result["Operation result"] {
    <<enumeration>>
    SUCCESS
    FAILURE
}
Box --> Result : result
''',
    'styled': '''classDiagram
class Source {
    +String value
}
class Destination {
    +accept(value)
}
Source --> Destination : sends
style Source fill:#dbeafe,stroke:#2563eb,color:#1e3a8a,stroke-width:2px
style Destination fill:#dcfce7,stroke:#15803d,color:#14532d
''',
    'isolated': 'classDiagram\nclass Standalone',
    'empty_compartments': '''---
config:
  class:
    hideEmptyMembersBox: true
---
classDiagram
class Named {
    +String name
}
class Empty
Named --> Empty
''',
}


def export(source, monkeypatch, **kwargs):
    graph = {}
    writer = api.build_connected_vsdx
    def capture(nodes, edges, **options):
        graph.update(nodes=nodes, edges=edges)
        return writer(nodes, edges, **options)
    monkeypatch.setattr(api, 'build_connected_vsdx', capture)
    with ZipFile(BytesIO(api.convert(source, format='vsdx', **kwargs))) as archive:
        assert archive.testzip() is None
        page = ET.fromstring(archive.read('visio/pages/page1.xml'))
    return graph, page


@pytest.mark.parametrize('name', SOURCES)
@pytest.mark.parametrize('theme', ['redux-color', 'dark'])
def test_class_export(name, theme, monkeypatch):
    graph, page = export(SOURCES[name], monkeypatch, theme=theme)
    nodes, edges = graph['nodes'], graph['edges']
    ids = {n['id']: str(i) for i,n in enumerate(nodes, 1)}
    shapes = {s.get('ID'):s for s in page.findall('v:Shapes/v:Shape', NS)}
    # Visio must not fall back to zero-width advances in sparse rich-text
    # rows, even when a tolerant viewer supplies its own spacing defaults.
    for shape in shapes.values():
        characters = {row.get('IX'): row for row in shape.findall("v:Section[@N='Character']/v:Row", NS)}
        for row in characters.values():
            assert row.find("v:Cell[@N='FontScale']", NS).get('V') == '1'
            assert row.find("v:Cell[@N='Letterspace']", NS).get('V') == '0'
        for run in shape.findall('v:Text/v:cp', NS):
            row = characters[run.get('IX')]
            assert float(row.find("v:Cell[@N='Size']", NS).get('V')) > 0
            assert run.tail and run.tail.strip()
    glue = page.findall('v:Connects/v:Connect', NS)
    assert len(glue) == 2*len(edges)
    marker_types = {'none': '0', 'extension': '14', 'aggregation': '22', 'composition': '0', 'dependency':'1', 'lollipop':'20'}
    for i, edge in enumerate(edges, len(nodes)+1):
        connections = [c for c in glue if c.get('FromSheet') == str(i)]
        assert [(c.get('FromCell'), c.get('ToSheet')) for c in connections] == [('BeginX',ids[edge['source']]),('EndX',ids[edge['target']])]
        assert len(edge['route']) >= 2
        assert all(isfinite(p[axis]) for p in edge['route'] for axis in ['x','y'])
        shape = shapes[str(i)]
        for side,field in [('begin','Begin'),('end','End')]:
            assert shape.find(f"v:Cell[@N='{field}Arrow']",NS).get('V') == marker_types[edge[side+'_marker']]
        if 'composition' in [edge['begin_marker'], edge['end_marker']]:
            assert len(shape.findall("v:Section[@N='Geometry']",NS)) == 1+sum(m == 'composition' for m in [edge['begin_marker'], edge['end_marker']])
            assert shape.find("v:Cell[@N='FillPattern']",NS).get('V') == '1'
    for node in nodes:
        shape = shapes[ids[node['id']]]
        assert len(shape.findall("v:Section[@N='Connection']/v:Row",NS)) >= 4
        if node['parent_id']:
            assert f"Sheet.{ids[node['parent_id']]}!SheetRef()" in shape.find("v:Cell[@N='Relationships']",NS).get('F')
        if node['shape'] == 'classBox':
            assert any(o['stroke'] for o in node['outlines'])
            text = ''.join(shape.find('v:Text',NS).itertext())
            for line in node['text_rows']:
                assert line['text'] in text
            assert len(shape.findall("v:Section[@N='Paragraph']/v:Row",NS)) == len(node['text_rows'])
    multiplicities = [s for s in shapes.values() if s.get('NameU','').startswith('Multiplicity')]
    assert len(multiplicities) == sum(len(e['terminal_labels']) for e in edges)
    for shape in multiplicities:
        assert '!BeginX' in shape.find("v:Cell[@N='PinX']",NS).get('F') or '!EndX' in shape.find("v:Cell[@N='PinX']",NS).get('F')
    if name == 'members':
        animal = shapes[ids['Animal']]
        assert len(animal.findall("v:Section[@N='Geometry']",NS)) >= 3
        styles = [row.find("v:Cell[@N='Style']",NS) for row in animal.findall("v:Section[@N='Character']/v:Row",NS)]
        assert any(s is not None and int(s.get('V')) & 4 for s in styles)
        assert any(s is not None and int(s.get('V')) & 2 for s in styles)
    if name == 'multiplicities':
        labels = {s.find('v:Text',NS).text for s in multiplicities}
        assert {'1','1..*','0..*','owner','accounts','related','previous'} <= labels
    if name == 'relationships':
        assert {e['begin_marker'] for e in edges} >= {'extension','composition','aggregation','lollipop'}
    if name == 'styled':
        assert shapes[ids['Source']].find("v:Cell[@N='FillForegnd']",NS).get('V') == '#DBEAFE'
        assert shapes[ids['Source']].find("v:Cell[@N='LineColor']",NS).get('V') == '#2563EB'


@pytest.mark.parametrize('routing', ['right-angle','straight','mermaid'])
def test_class_routing(routing, monkeypatch):
    graph, page = export(SOURCES['multiplicities'], monkeypatch, visio_connectors=routing)
    assert len(page.findall('v:Connects/v:Connect',NS)) == 8
    assert any(e['source'] == e['target'] and e['preserve_route'] for e in graph['edges'])


def test_class_self_loop_label_stays_clear(monkeypatch):
    graph, page = export(SOURCES['multiplicities'], monkeypatch)
    index = next(i for i,e in enumerate(graph['edges'], len(graph['nodes'])+1) if e['source'] == e['target'])
    shape = page.find(f"v:Shapes/v:Shape[@ID='{index}']",NS)
    loop_y = [float(c.get('V')) for c in shape.findall("v:Section[@N='Geometry'][@IX='0']/v:Row/v:Cell[@N='Y']",NS)]
    assert max(loop_y)-min(loop_y) > .1
    label_y = float(shape.find("v:Cell[@N='TxtPinY']",NS).get('V'))
    assert label_y > max(loop_y)+.2


def test_public_class_example():
    source = Path(__file__).parents[1].joinpath('examples/class.mmd').read_text()
    with ZipFile(BytesIO(api.convert(source, format='vsdx'))) as archive:
        page = ET.fromstring(archive.read('visio/pages/page1.xml'))
    text = '\n'.join(''.join(el.itertext()) for el in page.findall('.//v:Text',NS))
    assert all(word in text for word in ['Order','OrderLine','Product','Repository','SqlRepository','contains','1..*'])
