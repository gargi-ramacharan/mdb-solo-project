// Make invisible characters visible so the demo audience can actually see them.
export function revealInvisible(text: string) {
  return text
    .replace(/​/g, "⟦ZWSP⟧")
    .replace(/‌/g, "⟦ZWNJ⟧")
    .replace(/‍/g, "⟦ZWJ⟧")
    .replace(/⁠/g, "⟦WJ⟧")
    .replace(/﻿/g, "⟦BOM⟧")
    .replace(/­/g, "⟦SHY⟧");
}
