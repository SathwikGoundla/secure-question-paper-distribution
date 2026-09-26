interface EmptyStateProps {
  message: string;
}

/**
 * Renders a plain, honest "there is nothing here" message (e.g. "No
 * question papers found."). Deliberately has no illustration, chart,
 * or decorative content — an empty state should look like an empty
 * state, not a placeholder for fabricated data.
 */
export function EmptyState({ message }: EmptyStateProps) {
  return (
    <p className="empty-state" role="status">
      {message}
    </p>
  );
}
