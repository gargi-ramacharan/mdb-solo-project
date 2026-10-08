"""Page-preview overlay: rendering, box clamping, storage and the PNG endpoint (called directly, no HTTP client)."""
from pathlib import Path

import pymupdf
import pytest
from fastapi import HTTPException

import main
from scanner import overlay_box, scan_pdf

PDFS = Path(__file__).resolve().parents[2] / "test_pdfs"
PAGE = pymupdf.Rect(0, 0, 595, 842)


def load(name):
    return (PDFS / name).read_bytes()


def test_scan_without_page_images_is_unchanged():
    result = scan_pdf(load("poisoned_paper.pdf"), "p.pdf")
    assert result["pages"] == []


def test_flagged_pages_are_rendered_as_png():
    images = {}
    result = scan_pdf(load("poisoned_paper.pdf"), "p.pdf", page_images=images)
    assert result["pages"] == [{"page": 1, "width": 595.0, "height": 842.0}]
    assert images[1].startswith(b"\x89PNG")
    pix = pymupdf.Pixmap(images[1])
    assert abs(pix.width - 595 * 1.5) <= 1 and abs(pix.height - 842 * 1.5) <= 1


def test_clean_pdf_renders_nothing():
    images = {}
    result = scan_pdf(load("clean_paper.pdf"), "c.pdf", page_images=images)
    assert result["pages"] == [] and images == {}


def test_metadata_flags_have_no_overlay_box():
    result = scan_pdf(load("poisoned_resume.pdf"), "r.pdf", page_images={})
    meta = [f for f in result["flags"] if f["technique"] == "metadata"]
    assert meta and all(f["overlay_bbox"] is None for f in meta)
    assert all(f["overlay_bbox"] for f in result["flags"] if f["technique"] != "metadata")


@pytest.mark.parametrize("bbox,expected", [
    ((72, 700, 522, 725), [72, 700, 522, 725]),         # on the page: unchanged
    ((700, 389, 1090, 403), [587, 389, 595, 403]),      # entirely past the right edge -> strip on right edge
    ((72, 889, 355, 903), [72, 834, 355, 842]),         # entirely below the page -> strip on bottom edge
    ((-300, 100, -10, 112), [0, 100, 8, 112]),          # entirely left of the page -> strip on left edge
    ((500, 100, 700, 112), [500, 100, 595, 112]),       # partly off: clamped to the edge
])
def test_overlay_box_clamps_to_page(bbox, expected):
    box, _ = overlay_box(bbox, "off_page", PAGE)
    assert box == expected
    x0, y0, x1, y1 = box
    assert 0 <= x0 < x1 <= 595 and 0 <= y0 < y1 <= 842


def test_off_page_flag_marked():
    result = scan_pdf(load("offpage_trick.pdf"), "o.pdf", page_images={})
    assert result["flags"] and all(f["off_page"] for f in result["flags"])
    on_page = scan_pdf(load("poisoned_paper.pdf"), "p.pdf", page_images={})
    assert not any(f["off_page"] for f in on_page["flags"])


def test_run_scan_stores_images_and_endpoint_serves_them():
    result = main.run_scan(load("offpage_trick.pdf"), "o.pdf")
    sid = result["scan_id"]
    assert result["pages"][0]["image_url"] == f"/scan/{sid}/page/1.png"
    resp = main.page_image(sid, 1)
    assert resp.media_type == "image/png" and resp.body.startswith(b"\x89PNG")
    for bad in [(sid, 2), ("nope", 1)]:
        with pytest.raises(HTTPException) as e:
            main.page_image(*bad)
        assert e.value.status_code == 404


def test_images_evicted_with_scan(monkeypatch):
    monkeypatch.setattr(main, "MAX_SCANS", 1)
    first = main.run_scan(load("poisoned_paper.pdf"), "a.pdf")["scan_id"]
    main.run_scan(load("poisoned_paper.pdf"), "b.pdf")
    assert first not in main.SCANS and first not in main.PAGE_IMAGES
