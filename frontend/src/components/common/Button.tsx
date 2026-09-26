import type { ButtonHTMLAttributes } from "react";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  isLoading?: boolean;
  variant?: "primary" | "secondary";
}

export function Button({
  isLoading = false,
  variant = "primary",
  disabled,
  children,
  className = "",
  ...rest
}: ButtonProps) {
  return (
    <button
      className={`btn btn-${variant} ${className}`.trim()}
      disabled={disabled || isLoading}
      aria-busy={isLoading}
      {...rest}
    >
      {isLoading ? "Please wait…" : children}
    </button>
  );
}
