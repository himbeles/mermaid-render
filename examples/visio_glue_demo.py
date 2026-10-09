"""Windows-only proof of concept for a *semantic* Visio connector.

Requires installed desktop Visio and ``pip install pywin32``.
This demonstration does NOT inspect Mermaid semantics or modify the
geometry-based converter. It shows the COM glue step used by the proposal.
"""
from pathlib import Path

import win32com.client as win32

visio = win32.DispatchEx("Visio.Application")
visio.Visible = True

# Blank Visio document and two ordinary 2D shapes, coordinates in inches.
doc = visio.Documents.Add("")
page = visio.ActivePage
source = page.DrawRectangle(1, 4, 3, 5)
source.Text = "Input"
target = page.DrawRectangle(5, 4, 7, 5)
target.Text = "Processing"

# IMPORTANT: use Visio's native dynamic connector, NOT a generic polygon.
connector = page.Drop(visio.ConnectorToolDataObject, 4, 4.5)
connector.CellsU("BeginX").GlueTo(source.CellsU("PinX"))
connector.CellsU("EndX").GlueTo(target.CellsU("PinX"))
connector.CellsU("EndArrow").FormulaU = "13"

doc.SaveAs(str((Path.cwd() / "glued_connector.vsdx").resolve()))
print("Saved glued_connector.vsdx. Move either rectangle to verify that the edge follows it.")
