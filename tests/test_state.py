"""State diagrams retain semantic transitions and editable UML symbols."""
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pytest

from mermaid_render import api
from mermaid_render.vsdx import NS_MAIN

NS = {'v': NS_MAIN}
SOURCES = {
    'basic': '''stateDiagram-v2
[*] --> Idle
Idle --> Running : start
Running --> Idle : stop
Running --> [*]
''',
    'symbols': '''stateDiagram-v2
state Decide <<choice>>
state Split <<fork>>
state Merge <<join>>
[*] --> Decide
Decide --> Split : approved
Decide --> [*] : rejected
Split --> A
Split --> B
A --> Merge
B --> Merge
Merge --> [*]
''',
    'nested': '''stateDiagram-v2
[*] --> System
state System {
    [*] --> Running
    state Running {
        [*] --> Work
        Work --> Waiting : pause
        Waiting --> Work : resume
        Waiting --> [*] : done
    }
    Running --> [*]
}
System --> [*]
note right of Work : Processing data
''',
    'parallel': '''stateDiagram-v2
state Active {
    [*] --> A
    A --> B : finish A
    --
    [*] --> C
    C --> D : finish C
}
[*] --> Active
Active --> [*]
''',
    'descriptions': '''stateDiagram-v2
direction LR
state "Idle mode" as Idle
Idle : Waiting for command
Idle : entry / reset
[*] --> Idle
Idle --> Idle : poll
Idle --> [*]
''',
    'isolated': 'stateDiagram-v2\nstate "Power off" as Off',
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
def test_state_elements_and_transitions_survive(name, theme, monkeypatch):
    graph, page = export(SOURCES[name], monkeypatch, theme=theme)
    nodes, edges = graph['nodes'], graph['edges']
    shapes = page.findall('v:Shapes/v:Shape', NS)
    assert len(shapes) == len(nodes)+len(edges)
    connections = page.findall('v:Connects/v:Connect', NS)
    assert len(connections) == 2*len(edges)
    ids = {node['id']: str(index) for index, node in enumerate(nodes, 1)}
    indexed = {shape.get('ID'): shape for shape in shapes}
    for index, edge in enumerate(edges, len(nodes)+1):
        glue = [c for c in connections if c.get('FromSheet') == str(index)]
        assert [(c.get('FromCell'), c.get('ToSheet')) for c in glue] == [
            ('BeginX', ids[edge['source']]), ('EndX', ids[edge['target']])]
        assert len(edge['route']) >= 2
        connector = indexed[str(index)]
        assert connector.find("v:Cell[@N='EndArrow']", NS).get('V') == ('1' if edge['arrow'] else '0')
    for node in nodes:
        shape = indexed[ids[node['id']]]
        assert len(shape.findall("v:Section[@N='Connection']/v:Row", NS)) >= 4
        if node['is_group']:
            assert shape.find("v:Section[@N='User']/v:Row[@N='msvStructureType']", NS) is not None
        if node['parent_id']:
            relationships = shape.find("v:Cell[@N='Relationships']", NS).get('F')
            assert 'DEPENDSON(4,' in relationships
            assert f"Sheet.{ids[node['parent_id']]}!SheetRef()" in relationships
        if node['shape'] in {'state-start', 'state-end', 'diamond'} or node['id'] in {'Split','Merge'}:
            assert shape.find('v:Text', NS) is None
        if node['shape'] == 'state-end':
            assert len(shape.findall("v:Section[@N='Geometry']", NS)) == 2
            assert shape.find("v:Section[@N='Geometry'][@IX='0']/v:Cell[@N='NoFill']", NS).get('V') == '1'
            assert shape.find("v:Cell[@N='FillForegnd']", NS).get('V') != '#FFFFFF'
    if name == 'symbols':
        assert next(n for n in nodes if n['id'] == 'Decide')['shape'] == 'diamond'
    if name == 'nested':
        assert not any('----parent' in node['id'] for node in nodes)
        note = next(node for node in nodes if '----note' in node['id'])
        assert note['text'] == 'Processing data'
        assert note['parent_id'] == 'Running'
        attachment = next(e for e in edges if e['target'] == note['id'])
        assert attachment['dash'] and not attachment['arrow']
    if name == 'descriptions':
        state = next(node for node in nodes if node['id'] == 'Idle')
        assert state['text'] == 'Idle mode\nWaiting for command\nentry / reset'
        assert any(e['source'] == e['target'] and e['text'] == 'poll' for e in edges)
        state_shape = indexed[ids['Idle']]
        assert len(state_shape.findall("v:Section[@N='Paragraph']/v:Row", NS)) == 3
        assert len(state_shape.findall('v:Text/v:pp', NS)) == 3
        assert state_shape.find("v:Section[@N='Paragraph']/v:Row[@IX='0']/v:Cell[@N='SpAfter']", NS) is not None
    if name == 'isolated':
        assert len(nodes) == 1 and not edges


@pytest.mark.parametrize('routing', ['right-angle', 'straight', 'mermaid'])
def test_state_routing_and_final_glue(routing, monkeypatch):
    graph, page = export(SOURCES['basic'], monkeypatch, visio_connectors=routing)
    for edge in graph['edges']:
        if edge['text']:
            assert edge['label_bounds'] and edge['label_background']
    assert len(page.findall('v:Connects/v:Connect', NS)) == 8


def test_public_state_example():
    source = Path(__file__).parents[1].joinpath('examples/state.mmd').read_text()
    with ZipFile(BytesIO(api.convert(source, format='vsdx'))) as archive:
        page = ET.fromstring(archive.read('visio/pages/page1.xml'))
    labels = [el.text for el in page.findall('.//v:Text', NS)]
    assert {'Off', 'Starting', 'Running', 'Ready', 'Fault', 'reset', 'Processing data'} <= set(labels)
