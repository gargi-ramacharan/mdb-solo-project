"""Time each pipeline stage over a folder of PDFs.

    python benchmark.py [folder] [--provider anthropic|ollama] [--mock-llm] [--no-visual]

Runs scan + classify on every PDF (cold cache), then a second pass to show the cache-hit speedup.
--mock-llm swaps the real API for a fake with simulated latency, to measure batching/caching without
spending credits. Results are labeled as mock in the output.
The detector table compares the style checks with the OCR visual diff on every PDF.
"""
import argparse
import csv
import time
from pathlib import Path

import classifier_llm
from classifier_llm import LLMResult, classify_flags, get_classifier
from scanner import scan_pdf

FIELDS = ["provider", "filename", "pages", "num_flags", "parse_ms", "detect_ms", "visual_diff_ms", "llm_ms", "total_ms",
          "cache_hits", "final_risk"]
DETECTOR_FIELDS = ["style_only", "visual_only", "both"]

# PDFs with nothing hidden: any flag on these is a false positive. benign_hidden has hidden text on
# purpose (harmless), so it's neither a clean PDF nor an attack.
CLEAN_PDFS = {"clean_paper.pdf", "resume.pdf"}
NOT_ATTACKS = CLEAN_PDFS | {"benign_hidden.pdf"}


class MockLLM:
    """Stand-in for the API: fixed latency per call, labels everything "suspicious"."""

    name = "mock"

    LATENCY_S = 0.6

    def classify_batch(self, texts):
        time.sleep(self.LATENCY_S)
        return [LLMResult("suspicious", "mock") for _ in texts]


def detector_counts(flags: list[dict]) -> dict:
    by = [set(f["detected_by"]) for f in flags]
    return {"style_only": sum(b == {"style"} for b in by),
            "visual_only": sum(b == {"visual"} for b in by),
            "both": sum(b == {"style", "visual"} for b in by)}


def run_pass(pdfs: list[Path], classifier, visual: bool = True) -> list[dict]:
    rows = []
    for pdf in pdfs:
        scan = scan_pdf(pdf.read_bytes(), pdf.name, visual=visual)
        llm = classify_flags(scan["flags"], classifier, use_env=False)
        t = scan["timings_ms"]
        rows.append({
            "provider": getattr(classifier, "name", "none"),
            "filename": pdf.name,
            "pages": scan["page_count"],
            "num_flags": len(scan["flags"]),
            "parse_ms": t["parse"],
            "detect_ms": t["detect"],
            "visual_diff_ms": t.get("visual_diff", 0.0),
            "llm_ms": llm["llm"],
            "total_ms": round(t["total"] + llm["llm"], 2),
            "cache_hits": llm["cache_hits"],
            "final_risk": llm["risk"],
            "_llm_calls": llm["llm_calls"],
            "_retries": llm["retries"],
            "_flags": scan["flags"],
            "_llm_error": llm["llm_error"],
            "_visual_status": scan["visual_diff"],
            **detector_counts(scan["flags"]),
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
    retries = sum(r["_retries"] for r in rows)
    errors = sorted({r["_llm_error"] for r in rows if r["_llm_error"]})
    print(f"LLM calls: {calls}   retries: {retries}" + (f"   LLM errors: {'; '.join(errors)}" if errors else ""))


def print_flags(rows: list[dict]) -> None:
    """One line per flag: what the rules said, what the LLM said, and what the report shows."""
    print("\nPer-flag labels (pass 1)")
    cols = ["file", "technique", "by", "text", "rule", "ai", "final", "status", "ai_reason"]
    lines = []
    for r in rows:
        for f in r["_flags"]:
            text = f["text"].encode("unicode_escape").decode()[:44]  # make invisible chars visible here too
            lines.append([r["filename"].removesuffix(".pdf"), f["technique"], "+".join(f["detected_by"]), text, f["rule_label"],
                          f["llm_label"] or "-", f["final_label"], f["llm_status"], (f["llm_reason"] or "")[:70]])
    widths = [max(len(c), *(len(l[i]) for l in lines)) for i, c in enumerate(cols)] if lines else [len(c) for c in cols]
    print("  ".join(c.ljust(w) for c, w in zip(cols, widths)))
    print("-" * (sum(widths) + 2 * len(widths)))
    for l in lines:
        print("  ".join(v.ljust(w) for v, w in zip(l, widths)))


def print_detectors(rows: list[dict]) -> None:
    """Which detector caught what, per PDF, and the headline numbers."""
    cols = ["filename", "kind", "style_only", "visual_only", "both", "visual_diff_ms", "caught_by"]
    lines = []
    for r in rows:
        kind = "clean" if r["filename"] in CLEAN_PDFS else "benign" if r["filename"] in NOT_ATTACKS else "attack"
        style, visual = r["style_only"] + r["both"], r["visual_only"] + r["both"]
        caught = "both" if style and visual else "style" if style else "visual" if visual else "none"
        if kind != "attack" and caught == "none":
            caught = "-"
        lines.append([r["filename"], kind, r["style_only"], r["visual_only"], r["both"], r["visual_diff_ms"], caught])
    widths = [max(len(c), *(len(str(l[i])) for l in lines)) for i, c in enumerate(cols)]
    print("\nDetectors: style checks vs OCR visual diff (flag counts)")
    print("  ".join(c.ljust(w) for c, w in zip(cols, widths)))
    print("-" * (sum(widths) + 2 * len(widths)))
    for l in lines:
        print("  ".join(str(v).ljust(w) for v, w in zip(l, widths)))

    statuses = {r["_visual_status"]["status"] for r in rows}
    if statuses != {"ok"}:
        errors = sorted({r["_visual_status"].get("error", "") for r in rows} - {""})
        print(f"visual diff status: {', '.join(sorted(statuses))}" + (f" ({'; '.join(errors)})" if errors else ""))
        return
    attacks = [r for r in rows if r["filename"] not in NOT_ATTACKS]
    visual_only = [r["filename"] for r in attacks if r["visual_only"] + r["both"] and not r["style_only"] + r["both"]]
    style_only = [r["filename"] for r in attacks if r["style_only"] + r["both"] and not r["visual_only"] + r["both"]]
    missed = [r["filename"] for r in attacks if not r["num_flags"]]
    clean = [r for r in rows if r["filename"] in CLEAN_PDFS]
    fp_visual = sum(r["visual_only"] + r["both"] for r in clean)
    fp_all = sum(r["num_flags"] for r in clean)
    ms = [r["visual_diff_ms"] for r in rows]
    print(f"\nThe visual diff caught {len(visual_only)} attack(s) the style checks missed "
          f"({', '.join(visual_only) or 'none'}), with {fp_visual} false positive(s) on {len(clean)} clean PDF(s).")
    print(f"Style checks alone caught {len(style_only)} attack(s) the visual diff missed ({', '.join(style_only) or 'none'}).")
    print(f"Attacks missed by both: {len(missed)}{' (' + ', '.join(missed) + ')' if missed else ''}. "
          f"All flags on clean PDFs: {fp_all}. Visual diff time: avg {sum(ms) / len(ms):.0f} ms, max {max(ms):.0f} ms per PDF.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", nargs="?", default=str(Path(__file__).resolve().parents[1] / "test_pdfs"))
    ap.add_argument("--provider", choices=["anthropic", "ollama"], help="overrides LLM_PROVIDER from .env")
    ap.add_argument("--mock-llm", action="store_true", help="use a fake LLM with simulated latency")
    ap.add_argument("--no-visual", action="store_true", help="skip the OCR visual diff")
    ap.add_argument("--csv", default="benchmark_results.csv")
    args = ap.parse_args()

    pdfs = sorted(Path(args.folder).glob("*.pdf"))
    if not pdfs:
        raise SystemExit(f"No PDFs in {args.folder}")
    classifier = MockLLM() if args.mock_llm else get_classifier(args.provider)
    mode = f"provider: {classifier.name}" if classifier else "no LLM configured: rule-based only"

    classifier_llm.clear_cache()
    visual = not args.no_visual
    cold = run_pass(pdfs, classifier, visual)
    print_table(f"Pass 1: cold cache ({mode})", cold)
    print_flags(cold)
    if visual:
        print_detectors(cold)
    with open(args.csv, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS + DETECTOR_FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(cold)
    print(f"wrote {args.csv}")

    warm = run_pass(pdfs, classifier, visual)
    print_table(f"Pass 2: warm cache ({mode})", warm)
    cold_llm, warm_llm = sum(r["llm_ms"] for r in cold), sum(r["llm_ms"] for r in warm)
    speedup = f"{cold_llm / warm_llm:.0f}x" if warm_llm > 0 else "n/a"
    print(f"\nTotal LLM stage time: cold {cold_llm:.1f} ms -> warm {warm_llm:.1f} ms (speedup {speedup})")


if __name__ == "__main__":
    main()
