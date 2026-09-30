import { useLocalSearchParams } from "expo-router";
import { ScrollView, StyleSheet, Text, View } from "react-native";

import { Badge } from "../../lib/Badge";
import { useScan } from "../../lib/store";
import { classColor, colors, mono, techniqueLabel } from "../../lib/theme";

// Make invisible characters visible so the demo audience can actually see them.
function revealInvisible(text: string) {
  return text
    .replace(/​/g, "⟦ZWSP⟧")
    .replace(/‌/g, "⟦ZWNJ⟧")
    .replace(/‍/g, "⟦ZWJ⟧")
    .replace(/⁠/g, "⟦WJ⟧")
    .replace(/﻿/g, "⟦BOM⟧")
    .replace(/­/g, "⟦SHY⟧");
}

export default function FlagDetail() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { result } = useScan();
  const flag = result?.flags.find((f) => f.id === id);

  if (!flag) {
    return (
      <View style={styles.container}>
        <Text style={styles.label}>Flag not found. Run a scan first.</Text>
      </View>
    );
  }

  const color = classColor[flag.classification];

  return (
    <ScrollView style={{ backgroundColor: colors.bg }} contentContainerStyle={styles.container}>
      <View style={styles.badges}>
        <Badge label={techniqueLabel[flag.technique] ?? flag.technique} color={colors.accent} />
        <Badge label={flag.classification} color={color} filled />
      </View>

      <Text style={styles.label}>HIDDEN TEXT</Text>
      <View style={[styles.textBox, { borderColor: color }]}>
        <Text style={styles.hiddenText} selectable>
          {flag.technique === "invisible_unicode" ? revealInvisible(flag.text) : flag.text}
        </Text>
      </View>

      <Text style={styles.label}>WHY IT WAS FLAGGED</Text>
      <Text style={styles.reason}>{flag.reason}</Text>

      <View style={styles.grid}>
        <Field label="TECHNIQUE" value={flag.technique} />
        <Field label="CLASSIFICATION" value={flag.classification} valueColor={color} />
        <Field label="PAGE" value={flag.technique === "metadata" ? "— (metadata)" : String(flag.page)} />
        <Field label="BBOX" value={flag.bbox ? `[${flag.bbox.map((v) => v.toFixed(1)).join(", ")}]` : "null"} />
      </View>
    </ScrollView>
  );
}

function Field({ label, value, valueColor }: { label: string; value: string; valueColor?: string }) {
  return (
    <View style={styles.field}>
      <Text style={styles.fieldLabel}>{label}</Text>
      <Text style={[styles.fieldValue, valueColor ? { color: valueColor } : null]}>{value}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { padding: 16, paddingBottom: 48, maxWidth: 720, width: "100%", alignSelf: "center" },
  badges: { flexDirection: "row", gap: 8, marginBottom: 8 },
  label: { color: colors.muted, fontSize: 11, fontWeight: "700", letterSpacing: 1.2, marginTop: 20, marginBottom: 8 },
  textBox: { backgroundColor: colors.surface, borderWidth: 1, borderRadius: 12, padding: 16 },
  hiddenText: { color: colors.text, fontFamily: mono, fontSize: 15, lineHeight: 22 },
  reason: { color: colors.text, fontSize: 14, lineHeight: 21 },
  grid: { flexDirection: "row", flexWrap: "wrap", gap: 10, marginTop: 24 },
  field: { backgroundColor: colors.surface, borderRadius: 10, padding: 12, borderWidth: 1, borderColor: colors.border, flexGrow: 1, flexBasis: "45%" },
  fieldLabel: { color: colors.muted, fontSize: 10, fontWeight: "700", letterSpacing: 1 },
  fieldValue: { color: colors.text, fontFamily: mono, fontSize: 13, marginTop: 4 },
});
