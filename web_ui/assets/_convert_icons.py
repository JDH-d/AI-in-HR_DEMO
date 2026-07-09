import os
from pathlib import Path

from PIL import Image
import cairosvg

base = Path(r"C:\\bot\\web_ui\\assets")

for name in ("user", "bot"):
    svg_path = base / f"{name}.svg"
    png_path = base / f"{name}.png"
    cairosvg.svg2png(url=str(svg_path), write_to=str(png_path), output_width=128, output_height=128)
    img = Image.open(png_path)
    img.save(png_path)

print("OK")
