interface ErrorBannerProps {
  message: string | null;
}

/**
 * Renders a user-facing error message (already sanitized by the API
 * client / ApiError — never a raw exception or stack trace). Renders
 * nothing when there is no message.
 */
export function ErrorBanner({ message }: ErrorBannerProps) {
  if (!message) return null;
  return (
    <div className="error-banner" role="alert">
      {message}
    </div>
  );
}
