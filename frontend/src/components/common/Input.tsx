import type { InputHTMLAttributes } from "react";

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label: string;
  id: string;
  errorMessage?: string;
}

/**
 * A labeled input with an accessible error message. Errors are
 * communicated both visually (text + red-tinted border via CSS) and
 * programmatically (aria-invalid + aria-describedby), so error state
 * is never conveyed by color alone.
 */
export function Input({ label, id, errorMessage, className = "", ...rest }: InputProps) {
  const describedBy = errorMessage ? `${id}-error` : undefined;
  return (
    <div className="form-field">
      <label htmlFor={id}>{label}</label>
      <input
        id={id}
        className={`text-input ${errorMessage ? "text-input-error" : ""} ${className}`.trim()}
        aria-invalid={Boolean(errorMessage)}
        aria-describedby={describedBy}
        {...rest}
      />
      {errorMessage && (
        <p id={`${id}-error`} className="field-error" role="alert">
          {errorMessage}
        </p>
      )}
    </div>
  );
}
