import { useContext } from "react";
import { AuthContext } from "../contexts/AuthContext";

/**
 * Access the authentication state/actions established by AuthProvider.
 * Throws clearly if used outside the provider, rather than silently
 * returning `undefined` fields to a component.
 */
export function useAuth() {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error("useAuth must be used within an AuthProvider.");
  }
  return context;
}
