import { router } from "expo-router";
import { useEffect, useRef, useState } from "react";
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";

import { Badge } from "../lib/Badge";
import { PageView, type PageMode, type PageViewHandle } from "../lib/PageView";
import { useScan } from "../lib/store";
import { classColor, colors, mono, riskStyle, techniqueLabel } from "../lib/theme";
import type { Technique } from "../lib/api";

export default function Report() {
  const { result, ai, aiTimings } = useScan();
  const [mode, setMode] = useState<PageMode>("see");
  const [highlightId, setHighlightId] = useState<string | null>(null);
  const scrollRef = useRef<ScrollView>(null);
  const pageViewRef = useRef<PageViewHandle>(null);
  const pageSectionY = useRef(0);
  const highlightTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  useEffect(() => {
    if (!result) router.replace("/");
  }, [result]);
  useEffect(() => () => clearTimeout(highlightTimer.current), []);
  if (!result) return null;

  const openFlag = (id: string) => router.push({ pathname: "/flag/[id]", params: { id } });

  // Card tap: scroll the page view to the flag's box and flash it. Flags without a box open details.
  const showOnPage = (id: string) => {
    const y = pageViewRef.current?.boxY(id);
    if (y == null) return openFlag(id);
    scrollRef.current?.scrollTo({ y: Math.max(pageSectionY.current + y - 80, 0), animated: true });
    setHighlightId(id);
    clearTimeout(highlightTimer.current);
    highlightTimer.current = setTimeout(() => setHighlightId(null), 2500);
  };

  const risk = riskStyle[result.risk];
  const counts = { manipulation: 0, suspicious: 0, benign: 0 };
  result.flags.forEach((f) => counts[f.final_label]++);
  const aiUnavailable = ai === "error" || (ai === "done" && result.flags.some((f) => f.llm_status === "unavailable"));

  return (
    <ScrollView ref={scrollRef} style={{ backgroundColor: colors.bg }} contentContainerStyle={styles.container}>
      <View style={[styles.banner, { borderColor: risk.color, backgroundColor: risk.color + "1A" }]}>
        <View style={[styles.bannerIcon, { backgroundColor: risk.color }]}>
          <Text style={styles.bannerIconText}>{risk.icon}</Text>
        </View>
        <View style={{ flex: 1 }}>
          <Text style={[styles.bannerTitle, { color: risk.color }]}>{risk.label}</Text>
          <Text style={styles.bannerSub} numberOfLines={1}>
            {result.filename} · {result.page_count} page{result.page_count === 1 ? "" : "s"}
          </Text>
          <Text style={styles.bannerCounts}>
            {result.summary.total_flags} hidden item{result.summary.total_flags === 1 ? "" : "s"}
            {result.summary.total_flags > 0 &&
              ` · ${counts.manipulation} manipulation · ${counts.suspicious} suspicious · ${counts.benign} benign`}
          </Text>
        </View>
      </View>

      <View style={styles.aiRow}>
        {ai === "pending" && <ActivityIndicator size="small" color={colors.accent} />}
        <Text style={styles.aiText}>
          {ai === "pending"
            ? "AI review in progress…"
            : aiUnavailable
              ? "AI review unavailable (rule-based only)"
              : ai === "done"
                ? "AI review complete"
                : ""}
        </Text>
      </View>
      <Text style={styles.timing}>
        Scan {Math.round(result.timings_ms.total)} ms
        {aiTimings && ` · AI review ${Math.round(aiTimings.llm)} ms`}
        {aiTimings && aiTimings.cache_hits > 0 && ` (${aiTimings.cache_hits} cached)`}
      </Text>

      {Object.keys(result.summary.by_technique).length > 0 && (
        <View style={styles.chips}>
          {(Object.entries(result.summary.by_technique) as [Technique, number][]).map(([t, n]) => (
            <View key={t} style={styles.chip}>
              <Text style={styles.chipText}>
                {techniqueLabel[t] ?? t} <Text style={{ color: colors.accent }}>{n}</Text>
              </Text>
            </View>
          ))}
        </View>
      )}

      {result.pages.length > 0 && (
        <View style={styles.section} onLayout={(e) => (pageSectionY.current = e.nativeEvent.layout.y)}>
          <View style={styles.sectionHead}>
            <Text style={styles.sectionTitle}>Page view</Text>
            <View style={styles.toggle}>
              {(["see", "ai"] as const).map((m) => (
                <Pressable
                  key={m}
                  onPress={() => setMode(m)}
                  accessibilityRole="button"
                  accessibilityState={{ selected: mode === m }}
                  style={[styles.toggleBtn, mode === m && styles.toggleOn]}
                >
                  <Text style={[styles.toggleText, mode === m && styles.toggleTextOn]}>
                    {m === "see" ? "What you see" : "What AI sees"}
                  </Text>
                </Pressable>
              ))}
            </View>
          </View>
          <PageView
            ref={pageViewRef}
            pages={result.pages}
            flags={result.flags}
            mode={mode}
            highlightId={highlightId}
            onPressFlag={openFlag}
          />
          <Text style={styles.hint}>Tap a box for details. Dashed boxes mark text placed off the page edge.</Text>
        </View>
      )}

      {result.flags.length === 0 ? (
        <Text style={styles.empty}>No hidden text found. What you see is what the AI sees.</Text>
      ) : (
        result.flags.map((f) => (
          <Pressable
            key={f.id}
            onPress={() => showOnPage(f.id)}
            style={({ pressed }) => [
              styles.card,
              { borderLeftColor: classColor[f.final_label] },
              f.id === highlightId && { borderColor: classColor[f.final_label] },
              pressed && { opacity: 0.7 },
            ]}
          >
            <Text style={styles.cardText} numberOfLines={3}>
              {f.text}
            </Text>
            <View style={styles.cardMeta}>
              <Badge label={techniqueLabel[f.technique] ?? f.technique} color={colors.accent} />
              <Badge label={f.final_label} color={classColor[f.final_label]} filled />
              <Text style={styles.page}>{f.technique === "metadata" ? "metadata" : `p. ${f.page}`}</Text>
              <Pressable onPress={() => openFlag(f.id)} hitSlop={8} accessibilityRole="button">
                <Text style={styles.details}>Details ›</Text>
              </Pressable>
            </View>
          </Pressable>
        ))
      )}

      <Pressable style={styles.again} onPress={() => router.dismissTo("/")}>
        <Text style={styles.againText}>Scan another PDF</Text>
      </Pressable>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { padding: 16, paddingBottom: 48, maxWidth: 720, width: "100%", alignSelf: "center" },
  banner: { flexDirection: "row", alignItems: "center", gap: 16, borderWidth: 1, borderRadius: 16, padding: 20 },
  bannerIcon: { width: 48, height: 48, borderRadius: 24, alignItems: "center", justifyContent: "center" },
  bannerIconText: { color: colors.bg, fontSize: 24, fontWeight: "900" },
  bannerTitle: { fontSize: 22, fontWeight: "800" },
  bannerSub: { color: colors.text, fontSize: 13, marginTop: 2, fontFamily: mono },
  bannerCounts: { color: colors.muted, fontSize: 12, marginTop: 6 },
  aiRow: { flexDirection: "row", alignItems: "center", gap: 8, marginTop: 12, minHeight: 20 },
  aiText: { color: colors.muted, fontSize: 13 },
  timing: { color: colors.muted, opacity: 0.8, fontSize: 11, marginTop: 2, fontFamily: mono },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: 8, marginTop: 16 },
  chip: { backgroundColor: colors.surfaceAlt, borderRadius: 999, paddingVertical: 6, paddingHorizontal: 12, borderWidth: 1, borderColor: colors.border },
  chipText: { color: colors.text, fontSize: 12, fontWeight: "600" },
  section: { marginTop: 20 },
  sectionHead: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 8, marginBottom: 10 },
  sectionTitle: { color: colors.text, fontSize: 16, fontWeight: "800" },
  toggle: { flexDirection: "row", backgroundColor: colors.surfaceAlt, borderRadius: 999, padding: 3, borderWidth: 1, borderColor: colors.border },
  toggleBtn: { paddingVertical: 6, paddingHorizontal: 12, borderRadius: 999 },
  toggleOn: { backgroundColor: colors.accent },
  toggleText: { color: colors.text, fontSize: 12, fontWeight: "700" },
  toggleTextOn: { color: colors.bg },
  hint: { color: colors.muted, fontSize: 11, marginTop: -6 },
  details: { color: colors.accent, fontSize: 12, fontWeight: "700" },
  empty: { color: colors.muted, textAlign: "center", marginTop: 40, fontSize: 15 },
  card: {
    backgroundColor: colors.surface, borderRadius: 12, padding: 14, marginTop: 12,
    borderWidth: 1, borderColor: colors.border, borderLeftWidth: 4,
  },
  cardText: { color: colors.text, fontFamily: mono, fontSize: 13, lineHeight: 19 },
  cardMeta: { flexDirection: "row", alignItems: "center", gap: 8, marginTop: 10 },
  page: { color: colors.muted, fontSize: 12, marginLeft: "auto", fontFamily: mono },
  again: { marginTop: 24, borderWidth: 1, borderColor: colors.border, borderRadius: 12, paddingVertical: 14, alignItems: "center" },
  againText: { color: colors.text, fontWeight: "700" },
});
