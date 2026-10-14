import React, { useEffect } from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "@/App";
import "@/index.css";
import { ThemeProvider } from "@/lib/theme-provider";
import { Auth0ProviderWithNavigation } from "@/lib/auth0-provider";
import { AuthProvider, useAuth } from "@/lib/auth-context";
import { setTokenProvider } from "@/lib/api";
import { PostHogProvider } from "@/lib/posthog-provider";

// Component to initialize the API with auth
function ApiAuthConnector({ children }: { children: React.ReactNode }) {
  const { getToken, clearToken, isReady } = useAuth();

  useEffect(() => {
    // Set the token provider to use auth context
    setTokenProvider({
      getToken,
      clearToken,
      isReady,
    });
  }, [clearToken, getToken, isReady]);

  return <>{children}</>;
}

type ContextDRootGlobal = typeof globalThis & {
  __contextdRoot?: ReturnType<typeof ReactDOM.createRoot>;
};

const rootElement = document.getElementById("root")!;
const rootGlobal = globalThis as ContextDRootGlobal;
const root = rootGlobal.__contextdRoot ?? ReactDOM.createRoot(rootElement);
rootGlobal.__contextdRoot = root;

root.render(
  <React.StrictMode>
    <PostHogProvider>
      <ThemeProvider defaultTheme="system" storageKey="contextd-ui-theme">
        <BrowserRouter future={{ v7_relativeSplatPath: true, v7_startTransition: true }}>
          <Auth0ProviderWithNavigation>
            <AuthProvider>
              <ApiAuthConnector>
                <App />
              </ApiAuthConnector>
            </AuthProvider>
          </Auth0ProviderWithNavigation>
        </BrowserRouter>
      </ThemeProvider>
    </PostHogProvider>
  </React.StrictMode>
);
