import { Stack } from "expo-router";
import { StatusBar } from "expo-status-bar";

import { APP_NAME } from "../../config";
import { ScanProvider } from "../lib/store";
import { colors } from "../lib/theme";

export default function RootLayout() {
  return (
    <ScanProvider>
      <StatusBar style="dark" />
      <Stack
        screenOptions={{
          headerStyle: { backgroundColor: colors.bg },
          headerTintColor: colors.text,
          headerTitleStyle: { fontWeight: "700" },
          headerShadowVisible: false,
          contentStyle: { backgroundColor: colors.bg },
        }}
      >
        <Stack.Screen name="index" options={{ title: APP_NAME, headerShown: false }} />
        <Stack.Screen name="scanning" options={{ title: "Scanning", headerBackVisible: false, gestureEnabled: false }} />
        <Stack.Screen name="report" options={{ title: "Report" }} />
        <Stack.Screen name="flag/[id]" options={{ title: "Flag detail" }} />
      </Stack>
    </ScanProvider>
  );
}
