import { router } from "expo-router";
import { useEffect } from "react";
import { Pressable, ScrollView, StyleSheet, Text, View } from "react-native";

import { Badge } from "../lib/Badge";
import { useScan } from "../lib/store";
import { classColor, colors, mono, riskStyle, techniqueLabel } from "../lib/theme";
import type { Technique } from "../lib/api";

export default function Report() {
  const { result } = useScan();

  useEffect(() => {
    if (!result) router.replace("/");
  }, [result]);
  if (!result) return null;

  const risk = riskStyle[result.risk];
  const counts = { manipulation: 0, suspicious: 0, benign: 0 };
  result.flags.forEach((f) => counts[f.classification]++);

  return (
    <ScrollView style={{ backgroundColor: colors.bg }} contentContainerStyle={styles.container}>
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

      {result.flags.length === 0 ? (
        <Text style={styles.empty}>No hidden text found. What you see is what the AI sees.</Text>
      ) : (
        result.flags.map((f) => (
          <Pressable
            key={f.id}
            onPress={() => router.push({ pathname: "/flag/[id]", params: { id: f.id } })}
            style={({ pressed }) => [styles.card, { borderLeftColor: classColor[f.classification] }, pressed && { opacity: 0.7 }]}
          >
            <Text style={styles.cardText} numberOfLines={3}>
              {f.text}
            </Text>
            <View style={styles.cardMeta}>
              <Badge label={techniqueLabel[f.technique] ?? f.technique} color={colors.accent} />
              <Badge label={f.classification} color={classColor[f.classification]} filled />
              <Text style={styles.page}>{f.technique === "metadata" ? "metadata" : `p. ${f.page}`}</Text>
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
  chips: { flexDirection: "row", flexWrap: "wrap", gap: 8, marginTop: 16 },
  chip: { backgroundColor: colors.surfaceAlt, borderRadius: 999, paddingVertical: 6, paddingHorizontal: 12, borderWidth: 1, borderColor: colors.border },
  chipText: { color: colors.text, fontSize: 12, fontWeight: "600" },
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
