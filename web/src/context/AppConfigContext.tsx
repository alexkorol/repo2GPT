import {
  PropsWithChildren,
  createContext,
  useContext,
  useMemo,
} from "react";
import { ApiConfig } from "../api/client";
import { useLocalStorage } from "../hooks/useLocalStorage";

export interface AppConfig extends ApiConfig {
  geminiApiKey: string;
}

interface AppConfigContextValue {
  config: AppConfig;
  setApiBaseUrl: (value: string) => void;
  setApiKey: (value: string) => void;
  setGeminiApiKey: (value: string) => void;
  resetCredentials: () => void;
}

const defaultBaseUrl =
  (typeof import.meta !== "undefined" &&
    (import.meta as any).env?.VITE_API_BASE_URL) ||
  "http://localhost:8000";

const AppConfigContext = createContext<AppConfigContextValue | undefined>(
  undefined
);

export function AppConfigProvider({ children }: PropsWithChildren) {
  const [apiBaseUrl, setApiBaseUrl] = useLocalStorage<string>(
    "repo2gpt.apiBaseUrl",
    defaultBaseUrl
  );
  const [apiKey, setApiKey] = useLocalStorage<string>("repo2gpt.apiKey", "");
  const [geminiApiKey, setGeminiApiKey] = useLocalStorage<string>(
    "repo2gpt.geminiApiKey",
    ""
  );

  const config = useMemo<AppConfig>(() => {
    const normalizedBaseUrl = apiBaseUrl.replace(/\/$/, "");
    return {
      apiBaseUrl: normalizedBaseUrl || defaultBaseUrl,
      apiKey,
      geminiApiKey,
    };
  }, [apiBaseUrl, apiKey, geminiApiKey]);

  const value = useMemo<AppConfigContextValue>(
    () => ({
      config,
      setApiBaseUrl,
      setApiKey,
      setGeminiApiKey,
      resetCredentials: () => {
        setApiKey("");
        setGeminiApiKey("");
      },
    }),
    [config, setApiBaseUrl, setApiKey, setGeminiApiKey]
  );

  return (
    <AppConfigContext.Provider value={value}>
      {children}
    </AppConfigContext.Provider>
  );
}

export function useAppConfig(): AppConfigContextValue {
  const context = useContext(AppConfigContext);
  if (!context) {
    throw new Error("useAppConfig must be used within an AppConfigProvider");
  }
  return context;
}
