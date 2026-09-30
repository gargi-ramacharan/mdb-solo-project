import { createContext, ReactNode, useContext, useState } from "react";

import type { PickedFile, ScanResult } from "./api";

interface ScanState {
  file: PickedFile | null;
  setFile: (f: PickedFile | null) => void;
  result: ScanResult | null;
  setResult: (r: ScanResult | null) => void;
}

const ScanContext = createContext<ScanState | null>(null);

export function ScanProvider({ children }: { children: ReactNode }) {
  const [file, setFile] = useState<PickedFile | null>(null);
  const [result, setResult] = useState<ScanResult | null>(null);
  return <ScanContext.Provider value={{ file, setFile, result, setResult }}>{children}</ScanContext.Provider>;
}

export function useScan() {
  const ctx = useContext(ScanContext);
  if (!ctx) throw new Error("useScan must be used inside ScanProvider");
  return ctx;
}
