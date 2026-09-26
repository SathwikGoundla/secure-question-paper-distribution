interface LoadingIndicatorProps {
  label?: string;
}

export function LoadingIndicator({ label = "Loading…" }: LoadingIndicatorProps) {
  return (
    <div className="loading-indicator" role="status" aria-live="polite">
      <span className="spinner" aria-hidden="true" />
      <span>{label}</span>
    </div>
  );
}
