from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from scanner import scan_pdf

app = FastAPI(title="PDF scan API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/scan")
async def scan(file: UploadFile = File(...)):
    data = await file.read()
    if not data.startswith(b"%PDF"):
        raise HTTPException(status_code=400, detail="File is not a PDF")
    try:
        return scan_pdf(data, file.filename or "upload.pdf")
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Could not scan PDF: {e}")
