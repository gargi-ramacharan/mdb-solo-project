import { Platform } from "react-native";

import type { Classification, Risk, Technique } from "./api";

export const colors = {
  bg: "#FFF8E1",
  surface: "#FFF0F5",
  surfaceAlt: "#FFE4EE",
  border: "#F5C9D8",
  text: "#3E2B36",
  muted: "#8C7382",
  accent: "#E0628F",
  green: "#3E9A74",
  yellow: "#C98A0B",
  red: "#D6456B",
};

export const mono = Platform.select({ ios: "Menlo", android: "monospace", default: "ui-monospace, Menlo, monospace" });

export const riskStyle: Record<Risk, { color: string; label: string; icon: string }> = {
  clean: { color: colors.green, label: "Clean", icon: "✓" },
  suspicious: { color: colors.yellow, label: "Suspicious", icon: "!" },
  manipulation: { color: colors.red, label: "Manipulation found", icon: "✕" },
};

export const classColor: Record<Classification, string> = {
  manipulation: colors.red,
  suspicious: colors.yellow,
  benign: colors.muted,
};

export const techniqueLabel: Record<Technique, string> = {
  white_text: "Hidden color",
  tiny_font: "Tiny font",
  off_page: "Off-page",
  invisible_unicode: "Invisible Unicode",
  metadata: "Metadata",
  invisible_render: "Invisible render",
};
