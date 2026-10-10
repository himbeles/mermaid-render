"""Sequence semantics must survive native grouping and 1D glue export."""
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pytest

from mermaid_render import convert
from mermaid_render.vsdx import NS_MAIN

NS = {'v': NS_MAIN}


def page_for(source, **kwargs):
    with ZipFile(BytesIO(convert(source, format='vsdx', **kwargs))) as archive:
        assert archive.testzip() is None
        return ET.fromstring(archive.read('visio/pages/page1.xml'))


def value(shape, key):
    return shape.find(f"v:Cell[@N='{key}']", NS).get('V')


@pytest.mark.parametrize('fixture', ['sequence-messages', 'sequence-interactions', 'sequence-lifecycle'])
def test_sequence_participants_group_their_artwork_and_keep_message_glue(fixture):
    source = Path(__file__).with_name('fixtures').joinpath(fixture+'.mmd').read_text()
    page = page_for(source)
    shapes = page.findall('v:Shapes/v:Shape', NS)
    participants = {s.get('ID'): s for s in shapes if s.get('NameU', '').startswith('Participant.')}
    messages = [s for s in shapes if s.get('NameU', '').startswith('Connector')]
    assert participants and messages
    ids = [s.get('ID') for s in page.findall('.//v:Shape', NS)]
    assert len(ids) == len(set(ids))
    names = [s.get('NameU') for s in shapes]
    assert len(names) == len(set(names))
    links = page.findall('v:Connects/v:Connect', NS)
    assert len(links) == 2*len(messages)
    for participant in participants.values():
        assert participant.get('Type') == 'Group'
        assert value(participant, 'SelectMode') == '0'
        assert len(participant.findall('v:Shapes/v:Shape', NS)) >= 3
        assert len(participant.findall("v:Section[@N='Connection']/v:Row", NS)) > 4
    for message in messages:
        assert value(message, 'ObjType') == '2'
        assert value(message, 'ConFixedCode') == '2'  # Keep its chronological row.
        pair = [link for link in links if link.get('FromSheet') == message.get('ID')]
        assert {link.get('FromCell') for link in pair} == {'BeginX', 'EndX'}
        for link in pair:
            participant = participants[link.get('ToSheet')]
            row_index = int(link.get('ToCell').split('X')[1])-1
            assert row_index >= 4
            row = participant.find(f"v:Section[@N='Connection']/v:Row[@IX='{row_index}']", NS)
            assert row is not None
            endpoint = message.find(f"v:Cell[@N='{link.get('FromCell')}']", NS)
            assert f"Sheet.{participant.get('ID')}!Connections.X{row_index+1}" in endpoint.get('F')
            # A translated participant moves this glued endpoint by exactly
            # the same amount; no child header/lifeline is moved independently.
            actual = float(value(participant, 'PinX'))-float(value(participant, 'LocPinX'))+float(row.find("v:Cell[@N='X']", NS).get('V'))
            assert float(endpoint.get('V')) == pytest.approx(actual, abs=2e-6)


def test_sequence_arrow_styles_multiline_labels_and_number_visibility():
    source = Path(__file__).with_name('fixtures').joinpath('sequence-messages.mmd').read_text()
    page = page_for(source)
    shapes = page.findall('v:Shapes/v:Shape', NS)
    messages = {s.findtext('v:Text', namespaces=NS): s for s in shapes if s.get('NameU', '').startswith('Connector')}
    assert len(messages) == 11
    size = messages['Solid arrow'].find("v:Section[@N='Character']/v:Row/v:Cell[@N='Size']", NS)
    assert float(size.get('V')) == pytest.approx(16/96, abs=1e-6)
    assert value(messages['Solid without arrow'], 'EndArrow') == '0'
    assert value(messages['Dashed without arrow'], 'LinePattern') == '2'
    assert value(messages['Solid arrow'], 'EndArrow') == '13'
    assert value(messages['Dashed reply'], 'LinePattern') == '2'
    assert value(messages['Async'], 'EndArrow') == '1'
    assert value(messages['Bidirectional'], 'BeginArrow') == '13'
    assert value(messages['Bidirectional'], 'EndArrow') == '13'
    for label in ['Solid cross', 'Dashed cross']:
        assert value(messages[label], 'EndArrow') == '0'
        assert len(messages[label].findall("v:Section[@N='Geometry']", NS)) == 2
    for label in ['Self call', 'Self reply\nsecond line']:
        shape = messages[label]
        assert len(shape.findall("v:Section[@N='Geometry']/v:Row", NS)) == 4
        assert value(shape, 'BeginY') != value(shape, 'EndY')
    numbers = [s for s in shapes if s.get('NameU', '').startswith('Sequence.Number.')]
    assert len(numbers) == 11
    assert [s.findtext('.//v:Text', namespaces=NS) for s in numbers] == [str(i*10) for i in range(1,12)]
    for number in numbers:
        children = number.findall('v:Shapes/v:Shape', NS)
        assert len(children) == 2  # Dark badge plus white number, both visible.
        assert value(children[0], 'FillPattern') == '1'
        assert 'BeginX' in number.find("v:Cell[@N='PinX']", NS).get('F')


@pytest.mark.parametrize('theme', ['redux-color', 'default'])
def test_sequence_notes_frames_and_activations_are_editable(theme):
    source = Path(__file__).with_name('fixtures').joinpath('sequence-interactions.mmd').read_text()
    page = page_for(source, theme=theme)
    texts = [e.text for e in page.findall('.//v:Text', NS)]
    for text in ['Client', 'API', 'Worker', 'Shared context', 'multiple lines', 'par', 'opt', 'loop', 'critical', 'break']:
        assert text in texts
    shapes = page.findall('v:Shapes/v:Shape', NS)
    assert any(s.get('NameU', '').startswith('Sequence.Note.') for s in shapes)
    frames = [s for s in shapes if s.get('NameU', '').startswith('Sequence.control-structure.')]
    assert len(frames) == 5
    assert all(s.get('Type') == 'Group' for s in frames)
    assert all(float(value(s, 'TextBkgndTrans')) == 1 for s in page.findall('.//v:Shape', NS) if s.find('v:Text', NS) is not None)


def test_sequence_without_messages_is_supported():
    page = page_for('sequenceDiagram\n participant A as Alice')
    assert page.find('v:Shapes/v:Shape', NS).get('NameU') == 'Participant.A'
    assert page.find('v:Connects', NS) is None


def test_sequence_lifelines_stop_at_visible_viewport_without_mirrored_actors():
    source = Path(__file__).with_name('fixtures').joinpath('sequence-lifecycle.mmd').read_text()
    page = page_for(source)
    participant = page.find("v:Shapes/v:Shape[@NameU='Participant.A']", NS)
    # Mermaid's DOM has a 2000px lifeline, clipped by a 442px SVG viewport.
    assert float(value(participant, 'Height')) < 5
