from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image, ImageDraw
from pypdf import PdfReader


root = Path(__file__).resolve().parent
pdf_path = root / "output" / "pdf" / "DeepSeek_DSH_深度剖析_2026-08-31.pdf"
out_dir = root / "tmp" / "pdfs" / "rendered"
out_dir.mkdir(parents=True, exist_ok=True)

pdf = pdfium.PdfDocument(pdf_path)
images = []
for index in range(len(pdf)):
    bitmap = pdf[index].render(scale=1.6)
    image = bitmap.to_pil().convert("RGB")
    path = out_dir / f"page-{index + 1:02d}.png"
    image.save(path, optimize=True)
    images.append(image)

thumb_w = 280
thumbs = []
for i, image in enumerate(images):
    ratio = thumb_w / image.width
    thumb = image.resize((thumb_w, int(image.height * ratio)), Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", (thumb.width + 18, thumb.height + 34), "#E9EDF3")
    canvas.paste(thumb, (9, 23))
    draw = ImageDraw.Draw(canvas)
    draw.text((9, 5), f"Page {i + 1}", fill="#142238")
    thumbs.append(canvas)

cols = 3
rows = (len(thumbs) + cols - 1) // cols
cell_w = max(t.width for t in thumbs)
cell_h = max(t.height for t in thumbs)
sheet = Image.new("RGB", (cols * cell_w, rows * cell_h), "#D5DCE6")
for i, thumb in enumerate(thumbs):
    sheet.paste(thumb, ((i % cols) * cell_w, (i // cols) * cell_h))
sheet.save(out_dir / "contact-sheet.png", optimize=True)

reader = PdfReader(pdf_path)
text = "\n".join(page.extract_text() or "" for page in reader.pages)
(out_dir / "extracted.txt").write_text(text, encoding="utf-8")
links = 0
for page in reader.pages:
    for annotation in page.get("/Annots", []):
        obj = annotation.get_object()
        if obj.get("/Subtype") == "/Link":
            links += 1

print(f"pages={len(reader.pages)} links={links} chars={len(text)}")
print(f"missing_glyph_markers={text.count('�') + text.count('□')}")
print(out_dir / "contact-sheet.png")
