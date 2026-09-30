"""Rule-based classifier for hidden text.

Swap `classify` for an LLM judge later: keep the same signature
(text, technique) -> (classification, reason_suffix).
"""
import re

MANIPULATION_PATTERNS = [
    r"ignore (all )?(previous|prior|above)",
    r"ignore all",
    r"disregard (all |the )?(previous|prior|above)",
    r"\byou are\b",
    r"as an ai",
    r"language model",
    r"\bllms?\b",
    r"\bai (screener|reviewer|assistant|model)",
    r"note to ai",
    r"\breviewers?\b",
    r"positive review",
    r"recommend accept",
    r"recommend(ing)? (this|the) (paper|candidate)",
    r"rate this",
    r"rank (them|this|him|her) (first|highest|top)",
    r"hire this candidate",
    r"best candidate",
    r"most qualified",
    r"highly qualified",
    r"do not mention",
    r"don't mention",
    r"system prompt",
    r"new instructions",
]

ACCESSIBILITY_HINTS = ["alt text", "image of", "figure", "logo", "decorative", "page ", "header", "footer"]

SEVERITY = {"benign": 0, "suspicious": 1, "manipulation": 2}


def classify(text: str, technique: str) -> tuple[str, str]:
    lowered = text.lower()
    hits = [p for p in MANIPULATION_PATTERNS if re.search(p, lowered)]
    if hits:
        phrase = re.search(hits[0], lowered).group(0)
        return "manipulation", f'Contains AI-directed instruction language (matched "{phrase}").'

    words = re.findall(r"[a-zA-Z]{2,}", text)
    if any(h in lowered for h in ACCESSIBILITY_HINTS) and len(words) <= 8:
        return "benign", "Looks like an accessibility label or layout artifact."
    if len(words) <= 2 and technique != "invisible_unicode":
        return "benign", "Very short and non-instructional."
    return "suspicious", "Hidden content that a human reader would not see, but no explicit AI instructions detected."
