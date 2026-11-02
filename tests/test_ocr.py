from unittest.mock import patch, MagicMock

import requests
from PIL import Image

from rpa1c import ocr


def _img(tmp_path):
    p = tmp_path / "a.png"
    Image.new("RGB", (50, 50), "white").save(p)
    return p


def test_xiaomi_engine(tmp_path):
    resp = MagicMock(status_code=200)
    resp.json.return_value = {"message": {"content": "Счёт № 5"}}
    with patch.object(ocr.requests, "post", return_value=resp) as post:
        assert ocr.scan_to_text(_img(tmp_path), {"engine": "xiaomi"}) == "Счёт № 5"
    assert post.call_args.kwargs["json"]["messages"][0]["images"]


def test_fallback_to_tesseract(tmp_path):
    with patch.object(ocr.requests, "post", side_effect=requests.ConnectionError()), \
         patch.object(ocr, "_tesseract_page", return_value="tess"):
        assert ocr.scan_to_text(_img(tmp_path), {"engine": "xiaomi"}) == "tess"


def test_pdf_pages(tmp_path):
    import pymupdf as fitz

    d = fitz.open()
    d.new_page().insert_text((72, 72), "Test")
    d.new_page()
    p = tmp_path / "a.pdf"
    d.save(str(p))
    pages = ocr._load_pages(p, {"dpi": 100})
    assert len(pages) == 2 and pages[0].size[0] > 100
