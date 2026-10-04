import uuid
from collections import OrderedDict

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from classifier_llm import classify_flags
from scanner import scan_pdf

app = FastAPI(title="PDF scan API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# In-memory scan store for POST /classify/{scan_id}. Bounded so a long-running demo server can't grow forever.
MAX_SCANS = 200
SCANS: "OrderedDict[str, dict]" = OrderedDict()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/scan")
async def scan(file: UploadFile = File(...)):
    data = await file.read()
    if not data.startswith(b"%PDF"):
        raise HTTPException(status_code=400, detail="File is not a PDF")
    try:
        result = scan_pdf(data, file.filename or "upload.pdf")
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Could not scan PDF: {e}")
    result["scan_id"] = uuid.uuid4().hex
    SCANS[result["scan_id"]] = result
    while len(SCANS) > MAX_SCANS:
        SCANS.popitem(last=False)
    return result


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
