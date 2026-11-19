"""Regenerate the logo images and app.ico from app/web/assets/logo-original.png."""
from pathlib import Path
from PIL import Image

A = Path(__file__).resolve().parent.parent / "app" / "web" / "assets"
src = Image.open(A / "logo-original.png").convert("RGBA")
side = max(src.size)
sq = Image.new("RGBA", (side, side), (255, 255, 255, 0))
sq.paste(src, ((side - src.width) // 2, (side - src.height) // 2))
sq.resize((512, 512), Image.LANCZOS).save(A / "logo.png", optimize=True)
sq.resize((96, 96), Image.LANCZOS).save(A / "logo-96.png", optimize=True)
sq.resize((64, 64), Image.LANCZOS).save(A / "favicon.png", optimize=True)
sq.save(A / "app.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print("Icons regenerated in", A)
