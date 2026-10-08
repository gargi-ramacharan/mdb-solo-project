import uuid
from collections import OrderedDict

from fastapi import FastAPI, File, HTTPException, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from classifier_llm import classify_flags
from scanner import scan_pdf

app = FastAPI(title="PDF scan API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# In-memory scan store for POST /classify/{scan_id} and the page previews. Bounded so a long-running
# demo server can't grow forever; a scan's page images are evicted together with the scan.
MAX_SCANS = 100
SCANS: "OrderedDict[str, dict]" = OrderedDict()
PAGE_IMAGES: dict[str, dict[int, bytes]] = {}  # scan_id -> page number -> PNG bytes


@app.get("/health")
def health():
    return {"status": "ok"}


def run_scan(data: bytes, filename: str) -> dict:
    """Scan, render flagged pages, store both, and return the response body."""
    images: dict[int, bytes] = {}
    result = scan_pdf(data, filename, page_images=images)
    scan_id = uuid.uuid4().hex
    result["scan_id"] = scan_id
    for p in result["pages"]:
        p["image_url"] = f"/scan/{scan_id}/page/{p['page']}.png"  # relative to the backend URL
    SCANS[scan_id] = result
    PAGE_IMAGES[scan_id] = images
    while len(SCANS) > MAX_SCANS:
        old, _ = SCANS.popitem(last=False)
        PAGE_IMAGES.pop(old, None)
    return result


@app.post("/scan")
async def scan(file: UploadFile = File(...)):
    data = await file.read()
    if not data.startswith(b"%PDF"):
        raise HTTPException(status_code=400, detail="File is not a PDF")
    try:
        return run_scan(data, file.filename or "upload.pdf")
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Could not scan PDF: {e}")


@app.get("/scan/{scan_id}/page/{page_num}.png")
def page_image(scan_id: str, page_num: int):
    png = PAGE_IMAGES.get(scan_id, {}).get(page_num)
    if png is None:
        raise HTTPException(status_code=404, detail="No preview for that scan/page")
    return Response(content=png, media_type="image/png", headers={"Cache-Control": "private, max-age=3600"})


@app.post("/classify/{scan_id}")
def classify(scan_id: str):
    # Plain `def`: FastAPI runs it in a worker thread, so the blocking LLM call doesn't stall /scan.
    result = SCANS.get(scan_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Unknown or expired scan_id")
    stats = classify_flags(result["flags"])
    result["risk"] = stats.pop("risk")
    result["llm_timings_ms"] = stats
    return {"scan_id": scan_id, "risk": result["risk"], "flags": result["flags"], "timings_ms": stats}
