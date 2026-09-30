import { StyleSheet, Text, View } from "react-native";

import { colors } from "./theme";

export function Badge({ label, color, filled }: { label: string; color: string; filled?: boolean }) {
  return (
    <View style={[styles.badge, { borderColor: color, backgroundColor: filled ? color : "transparent" }]}>
      <Text style={[styles.text, { color: filled ? colors.bg : color }]}>{label.toUpperCase()}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  badge: { borderWidth: 1, borderRadius: 6, paddingHorizontal: 8, paddingVertical: 3 },
  text: { fontSize: 10, fontWeight: "800", letterSpacing: 0.6 },
});
