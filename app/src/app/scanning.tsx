import { router } from "expo-router";
import { useEffect, useRef, useState } from "react";
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from "react-native";

import { scanPdf } from "../lib/api";
import { useScan } from "../lib/store";
import { colors, mono } from "../lib/theme";

const STEPS = ["Extracting text", "Checking styles", "Classifying"];
const STEP_MS = 700; // minimum time per step so the demo is readable even on a fast backend

export default function Scanning() {
  const { file, setResult } = useScan();
  const [step, setStep] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const started = useRef(false);

  useEffect(() => {
    if (!file) {
      router.replace("/");
      return;
    }
    if (started.current) return;
    started.current = true;

    const timer = setInterval(() => setStep((s) => Math.min(s + 1, STEPS.length - 1)), STEP_MS);
    const minDelay = new Promise((r) => setTimeout(r, STEP_MS * STEPS.length));

    Promise.all([scanPdf(file), minDelay])
      .then(([result]) => {
        setResult(result);
        router.replace("/report");
      })
      .catch((e) => setError(e?.message ?? "Scan failed"))
      .finally(() => clearInterval(timer));

    return () => clearInterval(timer);
  }, [file, setResult]);

  if (error) {
    return (
      <View style={styles.container}>
        <Text style={[styles.title, { color: colors.red }]}>Scan failed</Text>
        <Text style={styles.error}>{error}</Text>
        <Pressable style={styles.button} onPress={() => router.replace("/")}>
          <Text style={styles.buttonText}>Back</Text>
        </Pressable>
      </View>
    );
  }

  return (
    <View style={styles.container}>
      <ActivityIndicator size="large" color={colors.accent} />
      <Text style={styles.title}>Scanning</Text>
      <Text style={styles.file} numberOfLines={1}>{file?.name}</Text>
      <View style={styles.steps}>
        {STEPS.map((label, i) => {
          const state = i < step ? "done" : i === step ? "active" : "pending";
          return (
            <View key={label} style={styles.stepRow}>
              <Text style={[styles.stepIcon, { color: state === "pending" ? colors.border : colors.accent }]}>
                {state === "done" ? "✓" : state === "active" ? "›" : "·"}
              </Text>
              <Text style={[styles.stepText, state === "pending" && { color: colors.border }, state === "active" && { color: colors.text }]}>
                {label}
                {state === "active" ? "…" : ""}
              </Text>
            </View>
          );
        })}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg, alignItems: "center", justifyContent: "center", padding: 24 },
  title: { color: colors.text, fontSize: 24, fontWeight: "800", marginTop: 20 },
  file: { color: colors.muted, fontFamily: mono, fontSize: 13, marginTop: 6, maxWidth: 320 },
  steps: { marginTop: 32, gap: 14, minWidth: 220 },
  stepRow: { flexDirection: "row", alignItems: "center", gap: 12 },
  stepIcon: { fontFamily: mono, fontSize: 18, width: 18, textAlign: "center" },
  stepText: { color: colors.muted, fontSize: 16, fontFamily: mono },
  error: { color: colors.muted, textAlign: "center", marginTop: 12, marginBottom: 24 },
  button: { borderWidth: 1, borderColor: colors.border, paddingVertical: 12, paddingHorizontal: 32, borderRadius: 10 },
  buttonText: { color: colors.text, fontWeight: "700" },
});
