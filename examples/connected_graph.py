"""Cross-platform experimental native Visio connector example (no COM)."""
from pathlib import Path
from mermaid_render import build_connected_vsdx

nodes = [
    {"id": "A", "text": "Input", "x": 20, "y": 30, "width": 120, "height": 55},
    {"id": "B", "text": "Processing", "x": 230, "y": 30, "width": 145, "height": 55},
    {"id": "C", "text": "Output", "x": 470, "y": 30, "width": 120, "height": 55},
]
edges = [{"source": "A", "target": "B"}, {"source": "B", "target": "C"}]
Path("connected_graph.vsdx").write_bytes(build_connected_vsdx(nodes, edges))
