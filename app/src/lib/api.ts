import Constants from "expo-constants";
import { Platform } from "react-native";

import { BACKEND_PORT, BACKEND_URL_OVERRIDE } from "../../config";

export type Technique =
  | "white_text"
  | "tiny_font"
  | "off_page"
  | "invisible_unicode"
  | "metadata"
  | "invisible_render";
export type Classification = "manipulation" | "suspicious" | "benign";
export type Risk = "clean" | "suspicious" | "manipulation";

// pending: AI review not run yet · ok/cached: AI label applied · skipped: rules already say manipulation
// invalid: AI answer failed validation · unavailable: no key / API error (rule-based only)
export type LlmStatus = "pending" | "ok" | "cached" | "skipped" | "invalid" | "unavailable";

export interface Flag {
  id: string;
  page: number;
  text: string;
  technique: Technique;
  classification: Classification; // same as final_label
  rule_label: Classification;
  llm_label: Classification | null;
  final_label: Classification;
  llm_reason: string | null;
  llm_status: LlmStatus;
  reason: string;
  bbox: [number, number, number, number] | null;
}

export interface ScanResult {
  scan_id: string;
  filename: string;
  page_count: number;
  risk: Risk;
  summary: { total_flags: number; by_technique: Partial<Record<Technique, number>> };
  flags: Flag[];
  timings_ms: { parse: number; detect: number; rule_classify: number; total: number };
}

export interface ClassifyResult {
  scan_id: string;
  risk: Risk;
  flags: Flag[];
  timings_ms: { llm: number; cache_hits: number; llm_calls: number; llm_error: string | null };
}

export interface PickedFile {
  uri: string;
  name: string;
  mimeType?: string;
  file?: File; // web only
}

function resolveBackendUrl(): string {
  if (BACKEND_URL_OVERRIDE) return BACKEND_URL_OVERRIDE.replace(/\/$/, "");
  if (Platform.OS === "web") {
    const host = typeof window !== "undefined" ? window.location.hostname : "localhost";
    return `http://${host}:${BACKEND_PORT}`;
  }
  // e.g. "192.168.1.23:8081" — the IP Expo Go used to reach the dev server.
  const hostUri = Constants.expoConfig?.hostUri;
  const host = hostUri?.split(":")[0];
  return `http://${host || "localhost"}:${BACKEND_PORT}`;
}

export const BACKEND_URL = resolveBackendUrl();

export async function checkHealth(): Promise<boolean> {
  try {
    const controller = new AbortController();
    const t = setTimeout(() => controller.abort(), 4000);
    const res = await fetch(`${BACKEND_URL}/health`, { signal: controller.signal });
    clearTimeout(t);
    return res.ok;
  } catch {
    return false;
  }
}

export async function scanPdf(file: PickedFile): Promise<ScanResult> {
  const form = new FormData();
  if (Platform.OS === "web" && file.file) {
    form.append("file", file.file, file.name);
  } else {
    // React Native's FormData accepts {uri, name, type} objects for file uploads.
    form.append("file", { uri: file.uri, name: file.name, type: file.mimeType ?? "application/pdf" } as any);
  }
  const res = await fetch(`${BACKEND_URL}/scan`, { method: "POST", body: form });
  if (!res.ok) {
    let detail = `Server returned ${res.status}`;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {}
    throw new Error(detail);
  }
  return res.json();
}

export async function classifyScan(scanId: string): Promise<ClassifyResult> {
  const res = await fetch(`${BACKEND_URL}/classify/${scanId}`, { method: "POST" });
  if (!res.ok) throw new Error(`AI review failed (${res.status})`);
  return res.json();
}
