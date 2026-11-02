"""OCR сканов: PDF и изображения -> текст.

Движки (ocr.engine в config.yaml):
  xiaomi    - модель Xiaomi-OCR-0 (0.8B) через локальный сервер Ollama (по умолчанию);
  tesseract - классический Tesseract.
Если основной движок недоступен и задан ocr.fallback_tesseract: true, берётся Tesseract.
"""
import base64
import io
from pathlib import Path

import requests
from PIL import Image

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp"}

DEFAULT_PROMPT = (
    "Распознай документ целиком. Выведи весь текст в порядке чтения, "
    "таблицы - в формате Markdown. Ничего не добавляй и не пересказывай."
)


def _load_pages(path: Path, cfg: dict) -> list:
    ext = path.suffix.lower()
    if ext == ".pdf":
        import pymupdf as fitz  # PyMuPDF: не требует установки Poppler

        zoom = cfg.get("dpi", 300) / 72
        with fitz.open(str(path)) as doc:
            out = []
            for page in doc:
                pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
                out.append(Image.frombytes("RGB", (pix.width, pix.height), pix.samples))
        return out
    if ext in IMAGE_EXT:
        return [Image.open(path)]
    raise ValueError(f"Неподдерживаемый формат: {ext}")


def _to_png_b64(img: Image.Image, max_side: int) -> str:
    img = img.convert("RGB")
    if max_side and max(img.size) > max_side:
        img.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def _xiaomi_page(img: Image.Image, cfg: dict) -> str:
    x = cfg.get("xiaomi", {})
    url = x.get("url", "http://127.0.0.1:11434").rstrip("/") + "/api/chat"
    payload = {
        "model": x.get("model", "xiaomi-ocr-0"),
        "stream": False,
        "options": {"temperature": 0, "num_predict": x.get("max_tokens", 3000), "repeat_penalty": 1.1},
        "keep_alive": "30m",
        "messages": [
            {
                "role": "user",
                "content": x.get("prompt", DEFAULT_PROMPT),
                "images": [_to_png_b64(img, x.get("max_side", 1600))],
            }
        ],
    }
    r = requests.post(url, json=payload, timeout=x.get("timeout", 300))
    if r.status_code != 200:
        raise RuntimeError(f"Ollama {r.status_code}: {r.text[:300]}")
    return r.json().get("message", {}).get("content", "")


def _tesseract_page(img: Image.Image, cfg: dict) -> str:
    import pytesseract

    if cfg.get("tesseract_cmd"):
        pytesseract.pytesseract.tesseract_cmd = cfg["tesseract_cmd"]
    return pytesseract.image_to_string(img, lang=cfg.get("lang", "rus+eng"))


def scan_to_text(path: Path, cfg: dict, progress=None) -> str:
    pages = _load_pages(path, cfg)
    progress = progress or (lambda i, n: None)
    engine = cfg.get("engine", "xiaomi")
    if engine == "tesseract":
        return "\n".join(_tesseract_page(p, cfg) for p in pages)
    if engine != "xiaomi":
        raise ValueError(f"Неизвестный ocr.engine: {engine}")
    try:
        out = []
        for i, p in enumerate(pages, 1):
            progress(i, len(pages))
            out.append(_xiaomi_page(p, cfg))
        return "\n".join(out)
    except (requests.RequestException, RuntimeError):
        if not cfg.get("fallback_tesseract", True):
            raise
        return "\n".join(_tesseract_page(p, cfg) for p in pages)
