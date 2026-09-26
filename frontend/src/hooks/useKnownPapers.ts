import { useCallback, useEffect, useState } from "react";

/**
 * The backend does not expose a "list all papers" endpoint (verified
 * during Phase 6B inspection — see PROJECT_STATE.md Section 17; only
 * single-paper lookups exist: GET /papers/{paper_id} and
 * GET /papers/{paper_id}/status, LLD API-05/API-08). Rather than
 * inventing a list endpoint or fabricating rows, this hook keeps a
 * small, session-scoped record of papers the current admin has
 * genuinely seen via a real API response this session (register or
 * lookup) — every entry is real data returned by the backend, not
 * fabricated. It is explicitly NOT a substitute for a real paper
 * catalogue; the Question Papers page documents this limitation.
 */

const STORAGE_KEY = "qpaper_known_papers";
const MAX_ENTRIES = 25;

export interface KnownPaper {
  paper_id: string;
  subject: string;
  status: string;
  created_at: string;
}

function readStore(): KnownPaper[] {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as KnownPaper[];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function writeStore(papers: KnownPaper[]): void {
  try {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(papers));
  } catch {
    // sessionStorage unavailable/full — this is a convenience cache
    // only, so silently skipping persistence is acceptable here.
  }
}

export function useKnownPapers() {
  const [papers, setPapers] = useState<KnownPaper[]>(() => readStore());

  useEffect(() => {
    writeStore(papers);
  }, [papers]);

  const remember = useCallback((paper: KnownPaper) => {
    setPapers((prev) => {
      const withoutExisting = prev.filter((p) => p.paper_id !== paper.paper_id);
      return [paper, ...withoutExisting].slice(0, MAX_ENTRIES);
    });
  }, []);

  return { papers, remember };
}
