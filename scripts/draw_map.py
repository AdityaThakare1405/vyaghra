"""
Opens an interactive map in your browser where you can draw:
  1. The reserve boundary (use the rectangle tool)
  2. Each tiger's territory (use the polygon tool, draw a freeform curve)

When done, click the "Export" button (top-right of the drawing toolbar) —
this downloads a .geojson file to your Downloads folder containing
everything you drew, in the order you drew it. Then run
scripts/import_drawn_shapes.py to apply it to the project.
"""

import webbrowser
from pathlib import Path

import folium
from folium.plugins import Draw

# Centered roughly on the real Pench Tiger Reserve.
m = folium.Map(location=[21.70, 79.30], zoom_start=11)

Draw(
    export=True,
    filename="vyaghra_drawn_shapes.geojson",
    position="topright",
    draw_options={
        "polyline": False,
        "circle": False,
        "circlemarker": False,
        "marker": False,
        "polygon": {"allowIntersection": False, "showArea": True},
        "rectangle": {"showArea": True},
    },
    edit_options={"edit": True},
).add_to(m)

output_path = Path(__file__).resolve().parent.parent / "data" / "samples" / "draw_map.html"
m.save(str(output_path))

print(f"Map saved to: {output_path}")
print("Opening in your browser now...")
print()
print("INSTRUCTIONS:")
print("  1. Use the RECTANGLE tool (top-right toolbar) to draw the reserve boundary — draw it once.")
print("  2. Use the POLYGON tool to draw each tiger's territory as a freeform curved/irregular shape.")
print("     Draw one polygon per tiger, in this exact order: Virat, Bheem, Yuvraj, Bajirao.")
print("  3. When finished, click the EXPORT button in the toolbar — this downloads a .geojson file")
print("     to your Downloads folder (usually named 'vyaghra_drawn_shapes.geojson' or similar).")
print("  4. Then run: python -m scripts.import_drawn_shapes")

webbrowser.open(f"file://{output_path}")