import base64
import os
import uuid
from collections import OrderedDict
from typing import Literal

from fastapi import FastAPI, File, HTTPException, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field

import visual_diff
from classifier_llm import ai_review_status, classify_flags
from scanner import scan_pdf

app = FastAPI(title="Underline API")

# CORS: the deployed web app's origin(s) from ALLOWED_ORIGINS (comma-separated, e.g.
# "https://underline.vercel.app"), plus any localhost port for local dev. Native apps (Expo Go)
# don't send an Origin header, so CORS doesn't apply to them.
ALLOWED_ORIGINS = [o.strip().rstrip("/") for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o.strip()]
LOCALHOST_ORIGIN = r"^https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$"
app.add_middleware(CORSMiddleware, allow_origins=ALLOWED_ORIGINS, allow_origin_regex=LOCALHOST_ORIGIN,
                   allow_methods=["GET", "POST"], allow_headers=["*"])

# The API is stateless: /scan returns everything the app needs (flags, timings, page images as data
# URLs) and /classify takes the flags in the request body. Serverless instances don't share memory,
# so nothing may depend on a previous request.
#
# The in-memory store below is only an optional local cache for the legacy endpoints
# (POST /classify/{scan_id}, GET /scan/{scan_id}/page/{n}.png). Off on Vercel, on locally;
# override with SCAN_CACHE=true/false.
MAX_SCANS = 100
SCANS: "OrderedDict[str, dict]" = OrderedDict()
PAGE_IMAGES: dict[str, dict[int, bytes]] = {}  # scan_id -> page number -> JPEG bytes

# Vercel's response body limit is 4.5 MB. Page images beyond this budget (base64 characters)
# are left out (image: null); the app then draws the boxes on a blank page.
MAX_IMAGE_CHARS = 3_000_000


def _env_flag(name: str, default: bool) -> bool:
    value = os.environ.get(name, "").strip().lower()
    return default if not value else value not in ("0", "false", "no", "off")


def scan_cache_enabled() -> bool:
    return _env_flag("SCAN_CACHE", default=not os.environ.get("VERCEL"))


@app.get("/health")
def health():
    # Configuration only, no network calls: tells the app what this deployment can do.
    return {"status": "ok", "ai_review": ai_review_status(), "visual_diff": visual_diff.enabled()}


def run_scan(data: bytes, filename: str, visual: bool = True) -> dict:
    """Scan and return the full response body: flags, timings, and flagged pages as data URLs."""
    images: dict[int, bytes] = {}
    result = scan_pdf(data, filename, page_images=images, visual=visual)
    scan_id = uuid.uuid4().hex
    result["scan_id"] = scan_id
    result["ai_review"] = ai_review_status()
    cache = scan_cache_enabled()
    budget = MAX_IMAGE_CHARS
    for p in result["pages"]:
        encoded = base64.b64encode(images[p["page"]]).decode("ascii")
        p["image"] = f"data:image/jpeg;base64,{encoded}" if len(encoded) <= budget else None
        if p["image"]:
            budget -= len(encoded)
        if cache:
            p["image_url"] = f"/scan/{scan_id}/page/{p['page']}.png"  # legacy; relative to the backend URL
    if cache:
        SCANS[scan_id] = result
        PAGE_IMAGES[scan_id] = images
        while len(SCANS) > MAX_SCANS:
            old, _ = SCANS.popitem(last=False)
            PAGE_IMAGES.pop(old, None)
    return result


@app.post("/scan")
def scan(file: UploadFile = File(...), visual: bool = True):
    # Plain `def` so the OCR (seconds, CPU-bound) runs in a worker thread instead of blocking the event loop.
    # ?visual=false skips the OCR visual diff for a fast style-only scan.
    data = file.file.read()
    if not data.startswith(b"%PDF"):
        raise HTTPException(status_code=400, detail="File is not a PDF")
    try:
        return run_scan(data, file.filename or "upload.pdf", visual)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Could not scan PDF: {e}")


# --- AI review -------------------------------------------------------------------------------------------

MAX_CLASSIFY_FLAGS = 300
MAX_FLAG_TEXT = 20_000  # the LLM only ever sees the first 1000 chars (classifier_llm.MAX_SNIPPET_CHARS)


class FlagIn(BaseModel):
    """What /classify needs from each flag. It comes from the client, so it's untrusted: lengths are
    capped, the label must be a known one, and any other fields are dropped."""
    model_config = ConfigDict(extra="ignore")
    id: str = Field(min_length=1, max_length=64)
    text: str = Field(max_length=MAX_FLAG_TEXT)
    technique: str = Field(max_length=40)
    rule_label: Literal["benign", "suspicious", "manipulation"]


class ClassifyRequest(BaseModel):
    flags: list[FlagIn] = Field(max_length=MAX_CLASSIFY_FLAGS)


# What /classify returns per flag; the app merges these into its flags by id.
LLM_FIELDS = ("id", "rule_label", "llm_label", "llm_reason", "llm_status", "final_label", "classification")


@app.post("/classify")
def classify(body: ClassifyRequest):
    """Stateless AI review of the flags in the request body. Same pipeline as always: only
    suspicious/benign go to the LLM, its answers are validated, and the final label is
    max(rule_label, llm_label), so severity only goes up."""
    # Plain `def`: FastAPI runs it in a worker thread, so the blocking LLM call doesn't stall /scan.
    ids = [f.id for f in body.flags]
    if len(set(ids)) != len(ids):
        raise HTTPException(status_code=422, detail="Duplicate flag ids")
    flags = [f.model_dump() for f in body.flags]
    for f in flags:
        f["classification"] = f["final_label"] = f["rule_label"]
    stats = classify_flags(flags)
    risk = stats.pop("risk")
    return {"risk": risk, "flags": [{k: f[k] for k in LLM_FIELDS} for f in flags], "timings_ms": stats}


@app.post("/classify/{scan_id}")
def classify_cached(scan_id: str):
    """Legacy: AI review of a scan in the local cache. Not available when the cache is off (Vercel)."""
    result = SCANS.get(scan_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Unknown or expired scan_id (use POST /classify with the flags)")
    stats = classify_flags(result["flags"])
    result["risk"] = stats.pop("risk")
    result["llm_timings_ms"] = stats
    return {"scan_id": scan_id, "risk": result["risk"], "flags": result["flags"], "timings_ms": stats}


@app.get("/scan/{scan_id}/page/{page_num}.png")
def page_image(scan_id: str, page_num: int):
    """Legacy: page preview from the local cache. The /scan response already includes it as a data URL."""
    img = PAGE_IMAGES.get(scan_id, {}).get(page_num)
    if img is None:
        raise HTTPException(status_code=404, detail="No preview for that scan/page")
    media = "image/png" if img.startswith(b"\x89PNG") else "image/jpeg"
    return Response(content=img, media_type=media, headers={"Cache-Control": "private, max-age=3600"})
