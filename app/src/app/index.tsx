import * as DocumentPicker from "expo-document-picker";
import { router } from "expo-router";
import { useCallback, useEffect, useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { APP_NAME } from "../../config";
import { BACKEND_URL, checkHealth } from "../lib/api";
import { useScan } from "../lib/store";
import { colors, mono } from "../lib/theme";

type Status = "checking" | "online" | "offline";

export default function Home() {
  const { setFile, setResult } = useScan();
  const [status, setStatus] = useState<Status>("checking");

  const refresh = useCallback(async () => {
    setStatus("checking");
    setStatus((await checkHealth()) ? "online" : "offline");
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const pick = async () => {
    const res = await DocumentPicker.getDocumentAsync({ type: "application/pdf", copyToCacheDirectory: true });
    if (res.canceled || !res.assets?.length) return;
    const a = res.assets[0];
    setResult(null);
    setFile({ uri: a.uri, name: a.name, mimeType: a.mimeType, file: a.file });
    router.push("/scanning");
  };

  const dot = { checking: colors.yellow, online: colors.green, offline: colors.red }[status];

  return (
    <SafeAreaView style={styles.container}>
      <View style={styles.hero}>
        <View style={styles.logo}>
          <Text style={styles.logoText}>{"</>"}</Text>
        </View>
        <Text style={styles.title}>{APP_NAME}</Text>
        <Text style={styles.tagline}>See what AI sees.</Text>
        <Text style={styles.blurb}>
          Finds hidden prompts in PDFs — white-on-white text, microscopic fonts, off-page text, invisible Unicode, and
          metadata — that AI reviewers and screeners read but humans can’t see.
        </Text>
      </View>

      <Pressable
        onPress={pick}
        disabled={status === "offline"}
        style={({ pressed }) => [styles.button, pressed && { opacity: 0.8 }, status === "offline" && { opacity: 0.4 }]}
      >
        <Text style={styles.buttonText}>Scan a PDF</Text>
      </Pressable>

      <Pressable onPress={refresh} style={styles.status}>
        <View style={[styles.dot, { backgroundColor: dot }]} />
        <Text style={styles.statusText}>
          {status === "checking" ? "Connecting to backend…" : status === "online" ? "Backend online" : "Backend offline — tap to retry"}
        </Text>
      </Pressable>
      <Text style={styles.url}>{BACKEND_URL}</Text>
      {status === "offline" && (
        <Text style={styles.hint}>
          Is the server running? On a phone, it must be on the same Wi-Fi and the URL must be your computer’s LAN IP
          (see config.ts).
        </Text>
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg, padding: 24, justifyContent: "center", maxWidth: 560, width: "100%", alignSelf: "center" },
  hero: { alignItems: "center", marginBottom: 40 },
  logo: {
    width: 72, height: 72, borderRadius: 18, borderWidth: 1, borderColor: colors.accent,
    backgroundColor: colors.accent + "1A", alignItems: "center", justifyContent: "center", marginBottom: 20,
  },
  logoText: { color: colors.accent, fontSize: 24, fontWeight: "700", fontFamily: mono },
  title: { color: colors.text, fontSize: 32, fontWeight: "800", textAlign: "center", letterSpacing: -0.5 },
  tagline: { color: colors.accent, fontSize: 16, marginTop: 8, fontFamily: mono },
  blurb: { color: colors.muted, fontSize: 14, textAlign: "center", marginTop: 16, lineHeight: 21 },
  button: { backgroundColor: colors.accent, paddingVertical: 20, borderRadius: 14, alignItems: "center" },
  buttonText: { color: colors.bg, fontSize: 18, fontWeight: "800", letterSpacing: 0.3 },
  status: { flexDirection: "row", alignItems: "center", justifyContent: "center", marginTop: 24, gap: 8 },
  dot: { width: 8, height: 8, borderRadius: 4 },
  statusText: { color: colors.muted, fontSize: 13 },
  url: { color: colors.muted, opacity: 0.6, fontSize: 11, textAlign: "center", marginTop: 4, fontFamily: mono },
  hint: { color: colors.yellow, fontSize: 12, textAlign: "center", marginTop: 12, lineHeight: 18 },
});
