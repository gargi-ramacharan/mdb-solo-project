import type { ExpoConfig } from "expo/config";

import { APP_NAME } from "./config.ts";

const config: ExpoConfig = {
  name: APP_NAME,
  slug: APP_NAME.toLowerCase().replace(/[^a-z0-9]+/g, "-"),
  scheme: APP_NAME.toLowerCase().replace(/[^a-z0-9]+/g, ""),
  version: "1.0.0",
  orientation: "portrait",
  icon: "./assets/icon.png",
  userInterfaceStyle: "light",
  ios: { supportsTablet: true },
  android: {
    adaptiveIcon: {
      backgroundColor: "#FFF8E1",
      foregroundImage: "./assets/android-icon-foreground.png",
      backgroundImage: "./assets/android-icon-background.png",
      monochromeImage: "./assets/android-icon-monochrome.png",
    },
  },
  web: { favicon: "./assets/favicon.png", bundler: "metro" },
  plugins: ["expo-router", "expo-status-bar"],
};

export default config;
