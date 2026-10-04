"""Invisible-Unicode helpers shared by the scanner (detection), the rules, and the LLM annotation."""
from collections import Counter

INVISIBLE_CHARS = {
    "​": "ZERO WIDTH SPACE",
    "‌": "ZERO WIDTH NON-JOINER",
    "‍": "ZERO WIDTH JOINER",
    "⁠": "WORD JOINER",
    "﻿": "ZERO WIDTH NO-BREAK SPACE",
    "­": "SOFT HYPHEN",
}


def is_tag_char(c: str) -> bool:
    """Unicode tag characters (U+E0000-U+E007F): invisible, and they mirror ASCII."""
    return 0xE0000 <= ord(c) <= 0xE007F


def is_invisible(c: str) -> bool:
    return c in INVISIBLE_CHARS or is_tag_char(c)


def decode_tag_chars(text: str) -> str:
    """Decode tag characters to reveal the ASCII message they hide."""
    return "".join(chr(ord(c) - 0xE0000) for c in text if 0xE0020 <= ord(c) <= 0xE007E)


def count_invisible(text: str) -> int:
    return sum(1 for c in text if is_invisible(c))


def annotate_invisible(text: str) -> str:
    """Version of `text` an LLM can actually "see": every invisible character becomes a visible
    ⟦U+XXXX⟧ marker, preceded by a scanner note with the counts and any decoded tag-character text.

    Runs of tag characters collapse into one marker; their content is given decoded in the note
    (a 40-character hidden message would otherwise become 40 markers and eat the 1000-char budget).
    """
    out, i = [], 0
    while i < len(text):
        c = text[i]
        if is_tag_char(c):
            j = i
            while j < len(text) and is_tag_char(text[j]):
                j += 1
            out.append(f"⟦{j - i} TAG CHARS⟧")
            i = j
            continue
        out.append(f"⟦U+{ord(c):04X}⟧" if c in INVISIBLE_CHARS else c)
        i += 1

    counts = Counter(f"U+{ord(c):04X}" for c in text if c in INVISIBLE_CHARS)
    tags = sum(1 for c in text if is_tag_char(c))
    parts = [f"{k} x{n}" for k, n in sorted(counts.items())] + ([f"tag chars x{tags}"] if tags else [])
    note = f"[scanner note: {count_invisible(text)} invisible characters ({', '.join(parts) or 'none'})"
    decoded = decode_tag_chars(text)
    if decoded:
        note += f'; decoded hidden tag-character text: "{decoded}"'
    return note + "]\n" + "".join(out)
