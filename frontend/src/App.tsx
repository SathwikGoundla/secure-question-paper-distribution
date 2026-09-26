import { BrowserRouter } from "react-router-dom";
import { AuthProvider } from "./contexts/AuthContext";
import { AppHeader } from "./components/layout/AppHeader";
import { AppRoutes } from "./routes/AppRoutes";

export function App() {
  return (
    <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <AuthProvider>
        <AppHeader />
        <AppRoutes />
      </AuthProvider>
    </BrowserRouter>
  );
}
