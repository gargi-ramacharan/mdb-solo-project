"""Time each pipeline stage over a folder of PDFs.

    python benchmark.py [folder] [--provider anthropic|ollama] [--mock-llm]

Runs scan + classify on every PDF (cold cache), then a second pass to show the cache-hit speedup.
--mock-llm swaps the real API for a fake with simulated latency, to measure batching/caching without
spending credits. Results are labeled as mock in the output.
"""
import argparse
import csv
import time
from pathlib import Path

import classifier_llm
from classifier_llm import LLMResult, classify_flags, get_classifier
from scanner import scan_pdf

FIELDS = ["provider", "filename", "pages", "num_flags", "parse_ms", "detect_ms", "llm_ms", "total_ms", "cache_hits", "final_risk"]


class MockLLM:
    """Stand-in for the API: fixed latency per call, labels everything "suspicious"."""

    name = "mock"

    LATENCY_S = 0.6

    def classify_batch(self, texts):
        time.sleep(self.LATENCY_S)
        return [LLMResult("suspicious", "mock") for _ in texts]


def run_pass(pdfs: list[Path], classifier) -> list[dict]:
    rows = []
    for pdf in pdfs:
        scan = scan_pdf(pdf.read_bytes(), pdf.name)
        llm = classify_flags(scan["flags"], classifier, use_env=False)
        t = scan["timings_ms"]
        rows.append({
            "provider": getattr(classifier, "name", "none"),
            "filename": pdf.name,
            "pages": scan["page_count"],
            "num_flags": len(scan["flags"]),
            "parse_ms": t["parse"],
            "detect_ms": t["detect"],
            "llm_ms": llm["llm"],
            "total_ms": round(t["total"] + llm["llm"], 2),
            "cache_hits": llm["cache_hits"],
            "final_risk": llm["risk"],
            "_llm_calls": llm["llm_calls"],
            "_llm_error": llm["llm_error"],
        })
    return rows


def print_table(title: str, rows: list[dict]) -> None:
    widths = {f: max(len(f), *(len(str(r[f])) for r in rows)) for f in FIELDS}
    line = "  ".join(f.ljust(widths[f]) for f in FIELDS)
    print(f"\n{title}\n{line}\n{'-' * len(line)}")
    for r in rows:
        print("  ".join(str(r[f]).ljust(widths[f]) for f in FIELDS))
    n = len(rows)
    avg = {f: round(sum(r[f] for r in rows) / n, 2) for f in FIELDS if f.endswith("_ms") or f in ("num_flags", "cache_hits")}
    print("-" * len(line))
    print("  ".join((f"{avg[f]}" if f in avg else ("AVERAGE" if f == "provider" else "")).ljust(widths[f]) for f in FIELDS))
    calls = sum(r["_llm_calls"] for r in rows)
    errors = sorted({r["_llm_error"] for r in rows if r["_llm_error"]})
    print(f"LLM calls: {calls}" + (f"   LLM errors: {'; '.join(errors)}" if errors else ""))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", nargs="?", default=str(Path(__file__).resolve().parents[1] / "test_pdfs"))
    ap.add_argument("--provider", choices=["anthropic", "ollama"], help="overrides LLM_PROVIDER from .env")
    ap.add_argument("--mock-llm", action="store_true", help="use a fake LLM with simulated latency")
    ap.add_argument("--csv", default="benchmark_results.csv")
    args = ap.parse_args()

    pdfs = sorted(Path(args.folder).glob("*.pdf"))
    if not pdfs:
        raise SystemExit(f"No PDFs in {args.folder}")
    classifier = MockLLM() if args.mock_llm else get_classifier(args.provider)
    mode = f"provider: {classifier.name}" if classifier else "no LLM configured: rule-based only"

    classifier_llm.clear_cache()
    cold = run_pass(pdfs, classifier)
    print_table(f"Pass 1: cold cache ({mode})", cold)
    with open(args.csv, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(cold)
    print(f"wrote {args.csv}")

    warm = run_pass(pdfs, classifier)
    print_table(f"Pass 2: warm cache ({mode})", warm)
    cold_llm, warm_llm = sum(r["llm_ms"] for r in cold), sum(r["llm_ms"] for r in warm)
    speedup = f"{cold_llm / warm_llm:.0f}x" if warm_llm > 0 else "n/a"
    print(f"\nTotal LLM stage time: cold {cold_llm:.1f} ms -> warm {warm_llm:.1f} ms (speedup {speedup})")


if __name__ == "__main__":
    main()
