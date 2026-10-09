"""PDF hidden-text detection using PyMuPDF."""
import time
import uuid

import pymupdf

from classifier import classify, classify_invisible, compute_risk
from invisible import INVISIBLE_CHARS, decode_tag_chars, is_tag_char

TINY_FONT_PT = 4.0
WHITE_THRESHOLD = 240
LOW_CONTRAST_RATIO = 1.5  # WCAG contrast ratio; 1.0 = identical colors, 21 = black on white


# Priority when a span triggers several techniques at once.
PRIORITY = ["invisible_render", "off_page", "white_text", "tiny_font"]

TECHNIQUE_REASONS = {
    "invisible_render": "Text is drawn with an invisible render mode or zero opacity, so it never appears on screen but is still extractable.",
    "off_page": "Text is positioned outside the visible page area, so a human never sees it but text extraction still picks it up.",
    "white_text": "Text color is (nearly) the same as the background behind it, making it invisible to a human reader.",
    "tiny_font": "Font size is below {pt}pt, too small for a human to read.",
    "invisible_unicode": "Text contains zero-width / invisible Unicode characters that humans can't see but AI models read.",
    "metadata": "Document metadata contains text a reader never sees on the page but that AI tools may ingest.",
}


def _rgb(color_int: int) -> tuple[int, int, int]:
    return (color_int >> 16) & 255, (color_int >> 8) & 255, color_int & 255


def _luminance(rgb) -> float:
    def ch(c):
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = rgb
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def _contrast(a, b) -> float:
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def _background_color(pix: pymupdf.Pixmap, bbox: pymupdf.Rect, scale: float):
    """Median color of the rendered pixels inside the span's bbox (glyphs are thin, so this is ~background)."""
    x0, y0 = max(int(bbox.x0 * scale), 0), max(int(bbox.y0 * scale), 0)
    x1, y1 = min(int(bbox.x1 * scale) + 1, pix.width), min(int(bbox.y1 * scale) + 1, pix.height)
    if x1 <= x0 or y1 <= y0:
        return None
    samples = []
    step = max(1, (x1 - x0) // 20)
    for y in range(y0, y1, max(1, (y1 - y0) // 5)):
        for x in range(x0, x1, step):
            samples.append(pix.pixel(x, y)[:3])
    if not samples:
        return None
    samples.sort(key=sum)
    return samples[len(samples) // 2]


def _is_layout_artifact(text: str, i: int) -> bool:
    """A lone zero-width char at a word boundary (line edge or next to whitespace) hides nothing.
    Google Docs exports put one after every line and bullet. Runs of several are still flagged,
    since sequences of zero-width chars can encode a message."""
    prev = text[i - 1] if i > 0 else " "
    nxt = text[i + 1] if i + 1 < len(text) else " "
    if prev in INVISIBLE_CHARS or nxt in INVISIBLE_CHARS:
        return False
    return prev.isspace() or nxt.isspace()


def find_invisible_unicode(text: str) -> tuple[list[str], str]:
    names = sorted({INVISIBLE_CHARS[c] for i, c in enumerate(text)
                    if c in INVISIBLE_CHARS and not _is_layout_artifact(text, i)})
    tags = decode_tag_chars(text)
    if any(is_tag_char(c) for c in text):
        names.append("UNICODE TAG CHARACTERS")
    return names, tags


def _overlap_ratio(a: pymupdf.Rect, b: pymupdf.Rect) -> float:
    if a.is_empty or a.get_area() == 0:
        return 0.0
    inter = pymupdf.Rect(a) & b
    return 0.0 if inter.is_empty else inter.get_area() / a.get_area()


def _invisible_trace_rects(page: pymupdf.Page) -> list[pymupdf.Rect]:
    """Rects of text drawn with render mode 3 (invisible) or zero opacity. Skips gracefully if unsupported."""
    try:
        return [
            pymupdf.Rect(t["bbox"])
            for t in page.get_texttrace()
            if t.get("type") == 3 or t.get("opacity", 1) == 0
        ]
    except Exception:
        return []


def _span_techniques(span, page_rect, pix, scale, invisible_rects) -> tuple[list[str], str]:
    """Return (techniques, extra detail) for one span."""
    bbox = pymupdf.Rect(span["bbox"])
    techniques, details = [], []

    if span.get("alpha", 255) == 0 or any(_overlap_ratio(bbox, r) > 0.5 for r in invisible_rects):
        techniques.append("invisible_render")

    if _overlap_ratio(bbox, page_rect) < 0.5:
        techniques.append("off_page")
        details.append(f"bbox {tuple(round(v) for v in bbox)} vs page {tuple(round(v) for v in page_rect)}")
    else:
        fg = _rgb(span["color"])
        bg = _background_color(pix, bbox, scale) if pix else None
        if bg is not None:
            ratio = _contrast(fg, bg)
            if ratio < LOW_CONTRAST_RATIO:
                techniques.append("white_text")
                details.append(f"text color rgb{fg} on background rgb{tuple(bg)}, contrast {ratio:.2f}:1")
        elif all(c > WHITE_THRESHOLD for c in fg):
            techniques.append("white_text")
            details.append(f"text color rgb{fg}")

    if span["size"] < TINY_FONT_PT:
        techniques.append("tiny_font")
        details.append(f"font size {span['size']:.1f}pt")

    techniques.sort(key=PRIORITY.index)
    return techniques, "; ".join(details)


def _make_flag(page_no, text, technique, bbox, extra_reason="", also=None):
    """Detection only; labels are added later by rule_classify() so its cost can be timed separately."""
    reason = TECHNIQUE_REASONS[technique].format(pt=TINY_FONT_PT)
    if extra_reason:
        reason += f" ({extra_reason})"
    if also:
        reason += f" Also: {', '.join(also)}."
    return {
        "id": uuid.uuid4().hex[:8],
        "page": page_no,
        "text": text.strip(),
        "technique": technique,
        "reason": reason,
        "bbox": [round(v, 1) for v in bbox] if bbox is not None else None,
    }


def scan_page(page: pymupdf.Page, page_no: int) -> list[dict]:
    flags = []
    # Don't clip to the mediabox, otherwise off-page text is silently dropped.
    text_flags = pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_MEDIABOX_CLIP
    data = page.get_text("dict", flags=text_flags, clip=pymupdf.INFINITE_RECT())
    scale = 1.0
    try:
        pix = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
    except Exception:
        pix = None
    invisible_rects = _invisible_trace_rects(page)

    for block in data["blocks"]:
        if block.get("type") != 0:
            continue
        run = None  # current merged run: {technique, text, bbox, details, also}

        def close_run():
            nonlocal run
            if run and run["text"].strip():
                flags.append(_make_flag(page_no, run["text"], run["technique"], run["bbox"],
                                        "; ".join(dict.fromkeys(d for d in run["details"] if d)),
                                        sorted(run["also"])))
            run = None

        for line in block["lines"]:
            line_text = "".join(s["text"] for s in line["spans"])
            names, tags = find_invisible_unicode(line_text)
            if names:
                shown, extra = line_text, "found: " + ", ".join(names)
                if tags:
                    extra += f'; decoded hidden tag text: "{tags}"'
                    shown = f"{line_text}\n[decoded tag text] {tags}"
                flag = _make_flag(page_no, shown, "invisible_unicode", pymupdf.Rect(line["bbox"]), extra)
                if tags:  # classify on the decoded message, which is what an AI would read
                    flag["_classify_text"] = tags
                flags.append(flag)
            for span in line["spans"]:
                text = span["text"]
                if not text.strip() or all(c in INVISIBLE_CHARS or ord(c) >= 0xE0000 for c in text.strip()):
                    continue  # blank, or only invisible chars (already covered by the line-level flag)

                techniques, detail = _span_techniques(span, page.rect, pix, scale, invisible_rects)
                if not techniques:
                    close_run()
                    continue
                primary = techniques[0]
                if run and run["technique"] == primary:
                    run["text"] += ("" if run["text"].endswith(" ") else " ") + text
                    run["bbox"] |= pymupdf.Rect(span["bbox"])
                    run["details"].append(detail)
                    run["also"].update(techniques[1:])
                else:
                    close_run()
                    run = {"technique": primary, "text": text, "bbox": pymupdf.Rect(span["bbox"]),
                           "details": [detail], "also": set(techniques[1:])}
        close_run()
    return flags


def scan_metadata(doc: pymupdf.Document) -> list[dict]:
    flags = []
    for key, value in (doc.metadata or {}).items():
        if not value or not isinstance(value, str) or key in ("format", "encryption", "creationDate", "modDate"):
            continue
        classification, _ = classify(value, "metadata")
        names, tags = find_invisible_unicode(value)
        # Plain short metadata (e.g. a normal title/author) is expected; only flag if it looks off.
        if classification == "manipulation" or names or len(value) > 200:
            flag = _make_flag(0, f"[{key}] {value}", "metadata", None, f"field: {key}")
            flags.append(flag)
    return flags


def rule_classify(flags: list[dict]) -> None:
    """Attach rule-based labels in place. `classification` is the label the app shows (final label)."""
    for f in flags:
        label, why = classify(f.pop("_classify_text", f["text"]), f["technique"])
        invisible = classify_invisible(f["text"])  # raw text, invisible chars intact
        if invisible and label != "manipulation":
            label, why = invisible
        f["reason"] += " " + why
        f["classification"] = f["rule_label"] = f["final_label"] = label
        f["llm_label"] = None
        f["llm_reason"] = None
        f["llm_status"] = "pending"


PREVIEW_ZOOM = 1.5
OFF_PAGE_STRIP_PT = 8.0  # how thick the edge marker for fully off-page text is, in PDF points


def overlay_box(bbox, technique: str, page_rect: pymupdf.Rect) -> tuple[list[float], bool]:
    """Box to draw on the page preview, in PDF points, always inside the page.
    Text that is (partly) off the page is clamped to the edge it overflows; text entirely off the page
    becomes a thin strip on that edge. Returns (box, off_page)."""
    x0, y0, x1, y1 = bbox
    W, H = page_rect.width, page_rect.height
    off_page = technique == "off_page" or x0 < 0 or y0 < 0 or x1 > W or y1 > H

    def clamp_axis(a0, a1, size):
        c0, c1 = min(max(a0, 0), size), min(max(a1, 0), size)
        if c1 - c0 < OFF_PAGE_STRIP_PT and (a0 >= size or a1 <= 0):
            # entirely past one edge: draw a strip along that edge
            return (size - OFF_PAGE_STRIP_PT, size) if a0 >= size else (0, OFF_PAGE_STRIP_PT)
        return c0, c1

    cx0, cx1 = clamp_axis(x0, x1, W)
    cy0, cy1 = clamp_axis(y0, y1, H)
    return [round(v, 1) for v in (cx0, cy0, cx1, cy1)], off_page


def render_flagged_pages(doc: pymupdf.Document, flags: list[dict], images: dict) -> list[dict]:
    """Render each page that has a boxed flag to PNG (into `images`, keyed by page number) and give every
    flag with a bbox an `overlay_bbox` / `off_page`. Flags without a bbox (metadata) get overlay_bbox None."""
    pages = []
    flagged = sorted({f["page"] for f in flags if f["bbox"] is not None and f["page"] >= 1})
    for f in flags:
        f["overlay_bbox"], f["off_page"] = None, False
    for n in flagged:
        page = doc[n - 1]
        rect = page.rect
        for f in flags:
            if f["page"] == n and f["bbox"] is not None:
                f["overlay_bbox"], f["off_page"] = overlay_box(f["bbox"], f["technique"], rect)
        pix = page.get_pixmap(matrix=pymupdf.Matrix(PREVIEW_ZOOM, PREVIEW_ZOOM), alpha=False)
        images[n] = pix.tobytes("png")
        pages.append({"page": n, "width": round(rect.width, 1), "height": round(rect.height, 1)})
    return pages


def scan_pdf(data: bytes, filename: str, page_images: dict | None = None) -> dict:
    """Scan a PDF. If `page_images` is a dict, flagged pages are also rendered into it as PNG bytes
    (page number -> bytes) and the result gets a `pages` list for the preview overlay."""
    t0 = time.perf_counter()
    doc = pymupdf.open(stream=data, filetype="pdf")
    t_parse = time.perf_counter()

    flags = scan_metadata(doc)
    for i, page in enumerate(doc):
        flags.extend(scan_page(page, i + 1))
    t_detect = time.perf_counter()

    rule_classify(flags)
    t_classify = time.perf_counter()

    pages = render_flagged_pages(doc, flags, page_images) if page_images is not None else []
    t_render = time.perf_counter()

    by_technique: dict[str, int] = {}
    for f in flags:
        by_technique[f["technique"]] = by_technique.get(f["technique"], 0) + 1

    ms = lambda a, b: round((b - a) * 1000, 2)
    result = {
        "filename": filename,
        "page_count": doc.page_count,
        "risk": compute_risk(f["final_label"] for f in flags),
        "summary": {"total_flags": len(flags), "by_technique": by_technique},
        "flags": flags,
        "pages": pages,
        "timings_ms": {
            "parse": ms(t0, t_parse),
            "detect": ms(t_parse, t_detect),
            "rule_classify": ms(t_detect, t_classify),
            "total": ms(t0, time.perf_counter()),
        },
    }
    if page_images is not None:
        result["timings_ms"]["render"] = ms(t_classify, t_render)
    doc.close()
    return result
