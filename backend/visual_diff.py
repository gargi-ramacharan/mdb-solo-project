"""OCR-based "visual diff": flag text that is in the PDF's text layer but not on the rendered page.

Style checks look at how text is drawn (color, size, position). They can't see text that is drawn
normally and then covered by a shape or an image, or clipped away by a clipping path. This module
renders each page, OCRs it with RapidOCR (what a human actually sees), and flags extracted spans
whose words OCR can't find where the span should be.

Coordinates: PyMuPDF gives span bboxes in PDF points (top-left origin, same as the rendered pixmap).
Rendering at ZOOM makes 1 pt = ZOOM px, so converting is a plain multiply/divide.

RapidOCR returns *lines* (a 4-point polygon + text), not words, and often drops the spaces inside a
line ("Westudytherobustness"). So matching works on normalized text without spaces: each span word
is looked for as a fuzzy substring of the OCR lines that overlap the span.

RapidOCR's line detector occasionally skips a perfectly visible line. So before a span is flagged,
it gets a second look: just its area is rendered and run through the recognizer alone. A crop with
almost no contrast (dark blue on dark blue) counts as blank, since the recognizer normalizes contrast
and would read text no human can.
"""
import re
import threading
from dataclasses import dataclass

import pymupdf
from rapidfuzz import fuzz

ZOOM = 2.0               # render scale for OCR (~144 dpi): small body text reads reliably
MIN_CHARS = 3            # spans with fewer normalized characters are skipped (OCR noise)
WORD_MATCH = 75          # rapidfuzz partial_ratio for a span word to count as "seen" in an OCR line
VISIBLE_THRESHOLD = 0.5  # a span is visually hidden if less than half of it is found
MIN_V_OVERLAP = 0.5      # an OCR line belongs to a span if they share half the shorter one's height
CROP_ZOOM = 3.0          # re-check render scale for a single span
MIN_CROP_CONTRAST = 40   # grayscale spread (0-255) below which a crop is unreadable to a human
MIN_REC_SCORE = 0.5      # RapidOCR recognition confidence below which the text is ignored


@dataclass
class OcrLine:
    text: str
    rect: pymupdf.Rect  # PDF points


class OcrUnavailable(RuntimeError):
    pass


# --- coordinates -----------------------------------------------------------------------------------------

def pdf_to_px(rect, zoom: float = ZOOM) -> tuple[float, float, float, float]:
    x0, y0, x1, y1 = rect
    return x0 * zoom, y0 * zoom, x1 * zoom, y1 * zoom


def polygon_to_pdf(points, zoom: float = ZOOM) -> pymupdf.Rect:
    """RapidOCR box (4 corner points in pixels, possibly slightly rotated) -> PDF-point bbox."""
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return pymupdf.Rect(min(xs) / zoom, min(ys) / zoom, max(xs) / zoom, max(ys) / zoom)


# --- text matching ---------------------------------------------------------------------------------------

def normalize(text: str) -> str:
    """Lowercase, letters/digits only. Drops punctuation, whitespace and invisible Unicode."""
    return "".join(c for c in text.lower() if c.isalnum())


def words(text: str) -> list[str]:
    return [w for w in (normalize(t) for t in re.split(r"\s+", text)) if w]


def lines_in_box(ocr: list[OcrLine], bbox) -> list[OcrLine]:
    """OCR lines that overlap the span: any horizontal overlap, and enough vertical overlap that
    they're the same line of text (not the line above or below)."""
    box = pymupdf.Rect(bbox)
    hits = []
    for line in ocr:
        inter = pymupdf.Rect(line.rect) & box
        if inter.is_empty or inter.width <= 0:
            continue
        if inter.height >= MIN_V_OVERLAP * min(box.height, line.rect.height):
            hits.append(line)
    return hits


def visible_fraction(span_text: str, seen: list[str]) -> float:
    """How much of the span OCR actually saw, 0..1, weighted by word length.

    `seen` is the text of the OCR lines overlapping the span. A word counts as seen if it appears in
    them as a fuzzy substring (tolerates OCR typos like rn/m, l/1 and missing spaces). Words under 4
    characters must appear exactly, since a fuzzy 2-letter match succeeds almost anywhere.
    """
    span_words = words(span_text)
    total = sum(len(w) for w in span_words)
    if not total:
        return 1.0
    joined = "".join(normalize(s) for s in seen)
    if not joined:
        return 0.0

    def is_seen(w: str) -> bool:
        return w in joined or (len(w) >= 4 and fuzz.partial_ratio(w, joined) >= WORD_MATCH)

    return sum(len(w) for w in span_words if is_seen(w)) / total


# --- OCR -------------------------------------------------------------------------------------------------

_engine = None
_engine_error: str | None = None
_engine_lock = threading.Lock()


def get_engine():
    """Load RapidOCR once (~10-15 s the first time: ONNX models) and reuse it. Raises OcrUnavailable."""
    global _engine, _engine_error
    with _engine_lock:
        if _engine is None and _engine_error is None:
            try:
                from rapidocr_onnxruntime import RapidOCR
                _engine = RapidOCR()
            except Exception as e:  # missing package, broken onnxruntime wheel, missing model files...
                _engine_error = f"RapidOCR failed to load: {type(e).__name__}: {e}"
        if _engine is None:
            raise OcrUnavailable(_engine_error)
        return _engine


def ocr_available() -> bool:
    try:
        get_engine()
        return True
    except OcrUnavailable:
        return False


def parse_rapidocr(result, zoom: float = ZOOM) -> list[OcrLine]:
    """RapidOCR output -> OcrLines. `result` is a list of [polygon, text, score], or None if no text."""
    return [OcrLine(text, polygon_to_pdf(box, zoom)) for box, text, _score in (result or []) if text.strip()]


def ocr_page(page: pymupdf.Page, zoom: float = ZOOM) -> list[OcrLine]:
    """Render the page and return OCR'd lines with PDF-point boxes."""
    import numpy as np

    engine = get_engine()
    pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    try:
        result, _elapsed = engine(img)
    except Exception as e:
        raise OcrUnavailable(f"RapidOCR failed on page {page.number + 1}: {type(e).__name__}: {e}") from e
    return parse_rapidocr(result, zoom)


def ocr_crop(page: pymupdf.Page, bbox, zoom: float = CROP_ZOOM) -> str:
    """Second look at one span: recognize just its area. Returns "" if nothing a human could read is there."""
    import numpy as np

    rect = (pymupdf.Rect(bbox) + (-2, -2, 2, 2)) & page.rect
    if rect.is_empty or rect.width < 1 or rect.height < 1:
        return ""  # off the page: nothing is drawn there
    pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), clip=rect, alpha=False)
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    gray = img.mean(axis=2)
    lo, hi = np.percentile(gray, [2, 98])
    if hi - lo < MIN_CROP_CONTRAST:
        return ""  # flat or near-flat area: no readable text
    try:
        result, _elapsed = get_engine()(img, use_det=False, use_cls=False, use_rec=True)
    except Exception as e:
        raise OcrUnavailable(f"RapidOCR failed on a crop of page {page.number + 1}: {type(e).__name__}: {e}") from e
    return " ".join(text for text, score in (result or []) if text and score >= MIN_REC_SCORE)


# --- detector --------------------------------------------------------------------------------------------

def _overlap(a: pymupdf.Rect, b) -> float:
    a = pymupdf.Rect(a)
    if a.is_empty or a.get_area() == 0:
        return 0.0
    inter = a & pymupdf.Rect(b)
    return 0.0 if inter.is_empty else inter.get_area() / a.get_area()


def hidden_spans(text_dict: dict, ocr: list[OcrLine], recheck=None) -> list[list[dict]]:
    """Runs of consecutive visually hidden spans (same block), each span as {text, bbox, visible}.
    `recheck(bbox) -> str` is the second look for spans the page OCR didn't find (see ocr_crop)."""
    runs, run = [], []
    for block in text_dict["blocks"]:
        if block.get("type") != 0:
            continue
        for line in block["lines"]:
            for span in line["spans"]:
                text = span["text"]
                if len(normalize(text)) < MIN_CHARS:
                    continue  # too short to judge; doesn't break a run either
                bbox = pymupdf.Rect(span["bbox"])
                vis = visible_fraction(text, [l.text for l in lines_in_box(ocr, bbox)])
                if vis < VISIBLE_THRESHOLD and recheck is not None:
                    vis = max(vis, visible_fraction(text, [recheck(bbox)]))
                if vis < VISIBLE_THRESHOLD:
                    run.append({"text": text, "bbox": bbox, "visible": vis})
                elif run:
                    runs.append(run)
                    run = []
        if run:
            runs.append(run)
            run = []
    return runs


def visual_diff_page(page: pymupdf.Page, page_no: int, text_dict: dict, flags: list[dict],
                     make_flag, ocr: list[OcrLine] | None = None) -> list[dict]:
    """New "visually_hidden" flags for one page. Spans already caught by a style check aren't
    duplicated; that flag gets "visual" added to its detected_by instead."""
    if ocr is None:
        ocr = ocr_page(page)
    recheck = (lambda bbox: ocr_crop(page, bbox)) if page is not None else None
    style_flags = [f for f in flags if f["page"] == page_no and f["bbox"] is not None]
    new = []
    for run in hidden_spans(text_dict, ocr, recheck):
        fresh = []
        for s in run:
            dup = next((f for f in style_flags if _overlap(s["bbox"], f["bbox"]) > 0.5), None)
            if dup is not None:
                if "visual" not in dup["detected_by"]:
                    dup["detected_by"].append("visual")
            else:
                fresh.append(s)
        if not fresh:
            continue
        bbox = pymupdf.Rect(fresh[0]["bbox"])
        for s in fresh[1:]:
            bbox |= s["bbox"]
        text = " ".join(s["text"].strip() for s in fresh)
        seen = round(100 * max(s["visible"] for s in fresh))
        flag = make_flag(page_no, text, "visually_hidden", bbox, f"OCR found {seen}% of it on the rendered page")
        flag["detected_by"] = ["visual"]
        new.append(flag)
    return new
