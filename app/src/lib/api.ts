import Constants from "expo-constants";
import { Platform } from "react-native";

import { BACKEND_PORT, BACKEND_URL_OVERRIDE } from "../../config";

export type Technique =
  | "white_text"
  | "tiny_font"
  | "off_page"
  | "invisible_unicode"
  | "metadata"
  | "invisible_render"
  | "visually_hidden";
export type Classification = "manipulation" | "suspicious" | "benign";
export type Risk = "clean" | "suspicious" | "manipulation";

// pending: AI review not run yet · ok/cached: AI label applied · skipped: rules already say manipulation
// invalid: AI answer failed validation · unavailable: no key / API error (rule-based only)
export type LlmStatus = "pending" | "ok" | "cached" | "skipped" | "invalid" | "unavailable";

// style: the rule checks on how text is drawn · visual: the OCR diff against the rendered page
export type Detector = "style" | "visual";

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
  overlay_bbox: [number, number, number, number] | null; // bbox clamped inside the page (PDF points); null = no box
  off_page: boolean; // text sits (partly) outside the page; the box marks the edge it overflows
  detected_by: Detector[];
}

export interface PagePreview {
  page: number;
  width: number; // PDF points
  height: number;
  image: string | null; // JPEG data URL; null if it didn't fit in the response size budget
}

export interface AiReviewStatus {
  enabled: boolean; // false: LLM_PROVIDER=none (or not configured), so the app skips the AI review
  provider: string | null;
  reason: string | null;
}

export interface ScanResult {
  scan_id: string;
  filename: string;
  page_count: number;
  risk: Risk;
  summary: { total_flags: number; by_technique: Partial<Record<Technique, number>> };
  flags: Flag[];
  pages: PagePreview[];
  timings_ms: {
    parse: number;
    detect: number;
    rule_classify: number;
    render?: number;
    visual_diff?: number;
    total: number;
  };
  visual_diff: { status: "ok" | "off" | "unavailable"; error?: string; pages_ocrd?: number };
  ai_review: AiReviewStatus;
}

// Per-flag AI fields returned by POST /classify, merged into the scan's flags by id.
export type ClassifiedFlag = Pick<
  Flag,
  "id" | "rule_label" | "llm_label" | "llm_reason" | "llm_status" | "final_label" | "classification"
>;

export interface ClassifyResult {
  risk: Risk;
  flags: ClassifiedFlag[];
  timings_ms: {
    llm: number;
    cache_hits: number;
    llm_calls: number;
    retries: number;
    llm_error: string | null;
    provider: string | null;
  };
}

export interface PickedFile {
  uri: string;
  name: string;
  mimeType?: string;
  size?: number; // bytes, when the picker reports it
  file?: File; // web only
}

// Set at build time for deployments, e.g. EXPO_PUBLIC_API_URL=https://underline-api.vercel.app
// (Expo inlines EXPO_PUBLIC_* variables into the bundle, so it must be written out in full like this.)
const API_URL_ENV = process.env.EXPO_PUBLIC_API_URL?.trim().replace(/\/$/, "") ?? "";

/** True when talking to a deployed backend (the online demo) rather than a local dev server. */
export const IS_REMOTE_API = API_URL_ENV !== "";

// Vercel rejects request bodies over 4.5 MB; leave room for the multipart overhead.
export const MAX_UPLOAD_BYTES = 4 * 1000 * 1000;
export const TOO_LARGE_MESSAGE = `This PDF is too large for the online demo (max ${MAX_UPLOAD_BYTES / 1e6} MB). Try a smaller file, or run Underline locally for big PDFs.`;

/** Error message if this file can't be uploaded to the current backend, else null. */
export function uploadSizeError(size: number | undefined): string | null {
  return IS_REMOTE_API && size != null && size > MAX_UPLOAD_BYTES ? TOO_LARGE_MESSAGE : null;
}

function resolveBackendUrl(): string {
  if (API_URL_ENV) return API_URL_ENV;
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
  if (res.status === 413) throw new Error(TOO_LARGE_MESSAGE);
  if (!res.ok) {
    let detail = `Server returned ${res.status}`;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {}
    throw new Error(detail);
  }
  return res.json();
}

/** What's left when there's no AI review, e.g. "rules + OCR only" (OCR = the visual diff ran). */
export function withoutAiLabel(scan: Pick<ScanResult, "visual_diff">): string {
  return scan.visual_diff?.status === "ok" ? "rules + OCR only" : "rules only";
}

/** Stateless AI review: send the flags themselves (the backend keeps no scan state between requests). */
export async function classifyFlags(flags: Flag[]): Promise<ClassifyResult> {
  const body = { flags: flags.map(({ id, text, technique, rule_label }) => ({ id, text, technique, rule_label })) };
  const res = await fetch(`${BACKEND_URL}/classify`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`AI review failed (${res.status})`);
  return res.json();
}
