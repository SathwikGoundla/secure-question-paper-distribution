import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Phase 6D — holds the backend-released PDF as a short-lived browser
 * object URL and guarantees it is revoked.
 *
 * Security properties:
 *  - The PDF Blob and its URL live only in React state / a ref for this
 *    component's lifetime. Nothing is written to localStorage,
 *    sessionStorage, IndexedDB or any other persistent store.
 *  - The URL is revoked when: a new file replaces it, `discard()` is
 *    called, the auto-expiry timer fires, or the component unmounts.
 */
const AUTO_DISCARD_MS = 5 * 60 * 1000;

export function useReleasedPaperFile() {
  const urlRef = useRef<string | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [objectUrl, setObjectUrl] = useState<string | null>(null);

  const discard = useCallback(() => {
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    if (urlRef.current !== null) {
      URL.revokeObjectURL(urlRef.current);
      urlRef.current = null;
    }
    setObjectUrl(null);
  }, []);

  const hold = useCallback(
    (blob: Blob) => {
      discard();
      const url = URL.createObjectURL(blob);
      urlRef.current = url;
      setObjectUrl(url);
      timerRef.current = setTimeout(discard, AUTO_DISCARD_MS);
    },
    [discard],
  );

  useEffect(() => discard, [discard]);

  return { objectUrl, hold, discard };
}
