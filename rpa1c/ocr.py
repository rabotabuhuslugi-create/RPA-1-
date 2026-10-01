"""OCR сканов: PDF и изображения -> текст."""
from pathlib import Path

import pytesseract
from PIL import Image

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp"}


def scan_to_text(path: Path, cfg: dict) -> str:
    if cfg.get("tesseract_cmd"):
        pytesseract.pytesseract.tesseract_cmd = cfg["tesseract_cmd"]
    lang = cfg.get("lang", "rus+eng")
    ext = path.suffix.lower()
    if ext == ".pdf":
        from pdf2image import convert_from_path

        pages = convert_from_path(
            str(path), dpi=cfg.get("dpi", 300), poppler_path=cfg.get("poppler_path")
        )
    elif ext in IMAGE_EXT:
        pages = [Image.open(path)]
    else:
        raise ValueError(f"Неподдерживаемый формат: {ext}")
    return "\n".join(pytesseract.image_to_string(p, lang=lang) for p in pages)
