import { useImperativeHandle, useRef, useState, type Ref } from "react";
import { Image, Pressable, StyleSheet, Text, View } from "react-native";

import { pageImageUrl, type Flag, type PagePreview } from "./api";
import { revealInvisible } from "./reveal";
import { classColor, colors, mono } from "./theme";

export type PageMode = "see" | "ai";

export interface PageViewHandle {
  /** Y offset of a flag's box from the top of the PageView, or null if it has no box. */
  boxY: (flagId: string) => number | null;
}

interface Props {
  pages: PagePreview[];
  flags: Flag[];
  mode: PageMode;
  highlightId: string | null;
  onPressFlag: (flagId: string) => void;
  ref?: Ref<PageViewHandle>;
}

const MIN_BOX_PX = 8; // tiny-font text can be ~2px tall; keep the box visible and tappable
const LABEL_MAX_H = 52;

/** Page previews with a box over every flag, scaled from PDF points to the displayed image. */
export function PageView({ pages, flags, mode, highlightId, onPressFlag, ref }: Props) {
  const [width, setWidth] = useState(0);
  const pageY = useRef<Record<number, number>>({}); // page block offset within the PageView
  const imageY = useRef<Record<number, number>>({}); // image offset within its page block

  const scaleFor = (p: PagePreview) => (width ? width / p.width : 0);

  useImperativeHandle(ref, () => ({
    boxY: (flagId) => {
      const f = flags.find((x) => x.id === flagId);
      const p = f?.overlay_bbox && pages.find((x) => x.page === f.page);
      if (!f?.overlay_bbox || !p) return null;
      return (pageY.current[p.page] ?? 0) + (imageY.current[p.page] ?? 0) + f.overlay_bbox[1] * scaleFor(p);
    },
  }));

  return (
    <View onLayout={(e) => setWidth(e.nativeEvent.layout.width)}>
      {width > 0 &&
        pages.map((p) => {
          const s = scaleFor(p);
          const h = p.height * s;
          const boxed = flags.filter((f) => f.page === p.page && f.overlay_bbox);
          return (
            <View key={p.page} style={styles.pageBlock} onLayout={(e) => (pageY.current[p.page] = e.nativeEvent.layout.y)}>
              <Text style={styles.caption}>
                Page {p.page} · {boxed.length} hidden item{boxed.length === 1 ? "" : "s"}
              </Text>
              <View
                style={[styles.imageWrap, { width, height: h }]}
                onLayout={(e) => (imageY.current[p.page] = e.nativeEvent.layout.y)}
              >
                <Image source={{ uri: pageImageUrl(p) }} style={{ width, height: h }} resizeMode="stretch" />
                {boxed.map((f) => (
                  <FlagBox key={f.id} flag={f} scale={s} pageW={width} pageH={h} mode={mode}
                           highlighted={f.id === highlightId} onPress={() => onPressFlag(f.id)} />
                ))}
              </View>
            </View>
          );
        })}
    </View>
  );
}

function FlagBox({ flag, scale, pageW, pageH, mode, highlighted, onPress }: {
  flag: Flag; scale: number; pageW: number; pageH: number; mode: PageMode; highlighted: boolean; onPress: () => void;
}) {
  const [x0, y0, x1, y1] = flag.overlay_bbox!;
  let left = x0 * scale, top = y0 * scale, w = (x1 - x0) * scale, h = (y1 - y0) * scale;
  if (h < MIN_BOX_PX) { top -= (MIN_BOX_PX - h) / 2; h = MIN_BOX_PX; }
  if (w < MIN_BOX_PX) { left -= (MIN_BOX_PX - w) / 2; w = MIN_BOX_PX; }
  left = Math.min(Math.max(left, 0), pageW - w);
  top = Math.min(Math.max(top, 0), pageH - h);

  const color = classColor[flag.final_label];
  const box = (
    <Pressable
      onPress={onPress}
      accessibilityRole="button"
      accessibilityLabel={`${flag.final_label} hidden text: ${flag.text.slice(0, 60)}`}
      style={[
        styles.box,
        { left, top, width: w, height: h, borderColor: color, backgroundColor: color + (highlighted ? "66" : "33") },
        flag.off_page && styles.offPage,
        highlighted && styles.highlighted,
      ]}
    />
  );
  if (mode === "see") return box;

  // "What AI sees": draw the hidden text in place, readable, starting at the box.
  const labelW = Math.min(pageW, Math.max(w, Math.min(260, pageW * 0.7)));
  const labelLeft = Math.min(left, pageW - labelW);
  const labelTop = Math.min(top, pageH - LABEL_MAX_H);
  const fontSize = Math.max(9, Math.min(13, h * 0.75));
  return (
    <>
      {box}
      <Pressable onPress={onPress} style={[styles.label, { left: labelLeft, top: labelTop, width: labelW, borderColor: color }]}>
        <Text style={[styles.labelText, { fontSize, lineHeight: fontSize * 1.25 }]} numberOfLines={3}>
          {revealInvisible(flag.text)}
        </Text>
      </Pressable>
    </>
  );
}

const styles = StyleSheet.create({
  pageBlock: { marginBottom: 16 },
  caption: { color: colors.muted, fontSize: 12, marginBottom: 6, fontFamily: mono },
  imageWrap: { backgroundColor: "#FFFFFF", borderRadius: 6, borderWidth: 1, borderColor: colors.border, overflow: "hidden" },
  box: { position: "absolute", borderWidth: 1.5, borderRadius: 2 },
  offPage: { borderStyle: "dashed", borderWidth: 2 },
  highlighted: { borderWidth: 3 },
  label: {
    position: "absolute", maxHeight: LABEL_MAX_H, backgroundColor: "rgba(255,255,255,0.94)",
    borderWidth: 1, borderRadius: 4, paddingHorizontal: 4, paddingVertical: 2, overflow: "hidden",
  },
  labelText: { color: "#1E1418", fontFamily: mono },
});
