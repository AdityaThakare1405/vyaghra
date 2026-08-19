"""
Opens an interactive map in your browser where you can hand-draw:
  1. The reserve boundary            -> RECTANGLE tool, draw it once
  2. (optional) The buffer zone      -> RECTANGLE tool, draw a second,
     bigger rectangle that fully encloses the reserve boundary. If you
     skip this, import_drawn_shapes.py will auto-generate a buffer zone
     by expanding the reserve boundary outward by RESERVE_BUFFER_WIDTH_KM
     (see src/config.py) — so drawing it yourself is optional, not required.
  3. Each tiger's territory          -> POLYGON tool, one freeform curve
     per tiger, drawn in the exact order listed below.

When done, click the "Export" button (top-right of the drawing toolbar) —
this downloads a .geojson file to your Downloads folder containing
everything you drew, in the order you drew it. Then run
scripts/import_drawn_shapes.py to apply it to the project.
"""

import webbrowser
from pathlib import Path

import folium
from folium.plugins import Draw

# Order matters: this is the order import_drawn_shapes.py will ask you to
# confirm your polygons against. Matches every tiger currently enrolled
# in the database — draw as many (or as few) as you like; anything left
# out keeps its existing occupancy snapshot untouched.
TIGER_ORDER = [
    "Virat", "Bheem", "Yuvraj", "Bajirao",
    "Machli", "Ustad", "Jai", "Sultan", "Collarwali", "Swastik",
]

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
output_path.parent.mkdir(parents=True, exist_ok=True)
m.save(str(output_path))

print(f"Map saved to: {output_path}")
print("Opening in your browser now...")
print()
print("INSTRUCTIONS:")
print("  1. RECTANGLE tool -> draw the reserve boundary once.")
print("  2. (Optional) RECTANGLE tool again -> draw a second, larger rectangle")
print("     fully enclosing the first, to define your own buffer zone. If you")
print("     skip this, a buffer zone is auto-generated for you on import.")
print("  3. POLYGON tool -> draw each tiger's territory as a freeform curved shape,")
print("     one polygon per tiger, in this exact order:")
for i, name in enumerate(TIGER_ORDER, 1):
    print(f"       {i}. {name}")
print("     (You can draw fewer than all 10 — any tiger you skip keeps its")
print("     existing occupancy data untouched.)")
print("  4. Click EXPORT in the toolbar — downloads a .geojson file to your")
print("     Downloads folder (usually named 'vyaghra_drawn_shapes.geojson').")
print("  5. Then run: python -m scripts.import_drawn_shapes")

webbrowser.open(f"file://{output_path}")