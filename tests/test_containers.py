"""Native Visio container membership must follow Mermaid's semantic hierarchy."""
from io import BytesIO
import re
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pytest

from mermaid_render import build_connected_vsdx, convert
from mermaid_render.vsdx import NS_MAIN

NS = {'v': NS_MAIN}


def page_for(data):
    with ZipFile(BytesIO(data)) as archive:
        assert archive.testzip() is None
        return ET.fromstring(archive.read('visio/pages/page1.xml'))


def value(shape, name):
    return shape.find(f"v:Cell[@N='{name}']", NS).get('V')


def relationships(shape):
    cell = shape.find("v:Cell[@N='Relationships']", NS)
    if cell is None:
        return {}
    return {int(kind): set(re.findall(r'Sheet\.(\d+)!SheetRef\(\)', members))
            for kind, members in re.findall(r'DEPENDSON\((\d+)((?:,Sheet\.\d+!SheetRef\(\))*)\)', cell.get('F'))}


@pytest.mark.parametrize('routing', ['right-angle', 'straight', 'mermaid'])
def test_nested_mermaid_containers_keep_membership_glue_and_stroke_widths(routing):
    source = '''flowchart LR
      subgraph Outer[Outer]
        A[Alpha] --> B[Beta]
        subgraph Inner[Inner]
          C[Gamma] --> D[Delta]
        end
      end
      B --> C
      D --> E[Outside]
      classDef thick fill:#dbeafe,stroke:#2563eb,stroke-width:2px
      class A,C thick
      style B stroke-width:0.5px
      linkStyle 0 stroke-width:3px
    '''
    page = page_for(convert(source, format='vsdx', visio_connectors=routing))
    shapes = page.findall('v:Shapes/v:Shape', NS)
    labels = {s.findtext('v:Text', namespaces=NS): s for s in shapes if s.find('v:Text', NS) is not None}
    ids = {label: s.get('ID') for label, s in labels.items()}
    connectors = [s for s in shapes if s.get('NameU', '').startswith('Connector')]
    assert len(shapes) == 11 and len(connectors) == 4
    for label in ['Outer', 'Inner']:
        container = labels[label]
        assert container.get('Type') == 'Shape'  # A container is not an XML group.
        user = container.find("v:Section[@N='User']/v:Row[@N='msvStructureType']/v:Cell[@N='Value']", NS)
        assert user.get('V') == 'Container' and user.get('F') == '"Container"'
        assert value(container, 'DisplayLevel') == '-1'
    assert relationships(labels['Alpha']) == {4: {ids['Outer']}}
    assert relationships(labels['Gamma']) == {4: {ids['Inner'], ids['Outer']}}
    assert relationships(labels['Outside']) == {}
    assert relationships(labels['Inner'])[4] == {ids['Outer']}
    assert relationships(connectors[0]) == {4: {ids['Outer']}}
    assert relationships(connectors[1]) == {4: {ids['Inner'], ids['Outer']}}
    assert relationships(connectors[2]) == {4: {ids['Outer']}}
    assert relationships(connectors[3]) == {}  # Crosses the outer boundary.
    assert relationships(labels['Inner'])[1] == {ids['Gamma'], ids['Delta'], connectors[1].get('ID')}
    members = {ids[label] for label in ['Inner', 'Alpha', 'Beta', 'Gamma', 'Delta']}
    members.update(s.get('ID') for s in connectors[:3])
    assert relationships(labels['Outer'])[1] == members
    links = page.findall('v:Connects/v:Connect', NS)
    assert len(links) == 8
    assert all(l.get('ToSheet') in {ids[label] for label in ['Alpha', 'Beta', 'Gamma', 'Delta', 'Outside']}
               for l in links)
    assert float(value(labels['Alpha'], 'LineWeight')) == pytest.approx(2/96, abs=1e-6)
    assert float(value(labels['Gamma'], 'LineWeight')) == pytest.approx(2/96, abs=1e-6)
    assert float(value(labels['Beta'], 'LineWeight')) == pytest.approx(.5/96, abs=1e-6)
    assert float(value(connectors[0], 'LineWeight')) == pytest.approx(3/96, abs=1e-6)


def test_empty_container_still_has_native_container_metadata():
    node = dict(id='Empty', x=0, y=0, width=200, height=100, is_group=True)
    page = page_for(build_connected_vsdx([node], []))
    assert relationships(page.find('v:Shapes/v:Shape', NS)) == {1: set()}


@pytest.mark.parametrize('parents', [('missing', None), ('B', None), ('B', 'A')])
def test_invalid_container_hierarchies_fail_clearly(parents):
    nodes = [dict(id='A', x=0, y=0, width=200, height=100, is_group=True, parent_id=parents[0]),
             dict(id='B', x=20, y=20, width=100, height=50, is_group=parents[1] is not None, parent_id=parents[1])]
    with pytest.raises(ValueError, match='parent|membership'):
        build_connected_vsdx(nodes, [])
