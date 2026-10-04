import { createContext, ReactNode, useCallback, useContext, useRef, useState } from "react";

import { classifyScan, type ClassifyResult, type PickedFile, type ScanResult } from "./api";

export type AiState = "idle" | "pending" | "done" | "error";

interface ScanState {
  file: PickedFile | null;
  setFile: (f: PickedFile | null) => void;
  result: ScanResult | null;
  setResult: (r: ScanResult | null) => void;
  ai: AiState;
  aiTimings: ClassifyResult["timings_ms"] | null;
  /** Fire-and-forget AI review. Rule-based results stay on screen; AI labels merge in when they arrive. */
  startAiReview: (scanId: string) => void;
}

const ScanContext = createContext<ScanState | null>(null);

export function ScanProvider({ children }: { children: ReactNode }) {
  const [file, setFile] = useState<PickedFile | null>(null);
  const [result, setResultState] = useState<ScanResult | null>(null);
  const [ai, setAi] = useState<AiState>("idle");
  const [aiTimings, setAiTimings] = useState<ClassifyResult["timings_ms"] | null>(null);
  const currentScan = useRef<string | null>(null);

  const setResult = useCallback((r: ScanResult | null) => {
    currentScan.current = r?.scan_id ?? null;
    setResultState(r);
    setAi("idle");
    setAiTimings(null);
  }, []);

  const startAiReview = useCallback((scanId: string) => {
    setAi("pending");
    classifyScan(scanId)
      .then((c) => {
        if (currentScan.current !== scanId) return; // user already started another scan
        setResultState((r) => (r && r.scan_id === scanId ? { ...r, risk: c.risk, flags: c.flags } : r));
        setAiTimings(c.timings_ms);
        setAi("done");
      })
      .catch(() => {
        if (currentScan.current === scanId) setAi("error");
      });
  }, []);

  return (
    <ScanContext.Provider value={{ file, setFile, result, setResult, ai, aiTimings, startAiReview }}>
      {children}
    </ScanContext.Provider>
  );
}

export function useScan() {
  const ctx = useContext(ScanContext);
  if (!ctx) throw new Error("useScan must be used inside ScanProvider");
  return ctx;
}
