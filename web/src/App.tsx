import { useState } from "react";
import {
  Navigate,
  Outlet,
  Route,
  Routes,
  useNavigate,
  useParams,
  useSearchParams,
} from "react-router-dom";
import { AppConfigProvider, useAppConfig } from "./context/AppConfigContext";
import { Dashboard } from "./components/Dashboard";
import { HeaderBar } from "./components/HeaderBar";
import { SettingsPanel } from "./components/SettingsPanel";
import { AuthPrompt } from "./components/AuthPrompt";
import "./styles/app.css";

function AppRoutes() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route index element={<DashboardPage />} />
        <Route path="jobs/:jobId" element={<DashboardPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

function AppLayout() {
  const { config } = useAppConfig();
  const [settingsOpen, setSettingsOpen] = useState<boolean>(!config.apiKey);

  return (
    <div className="app-shell">
      <HeaderBar onOpenSettings={() => setSettingsOpen(true)} />
      <main className="app-main">
        <Outlet />
      </main>
      <SettingsPanel open={settingsOpen} onClose={() => setSettingsOpen(false)} />
    </div>
  );
}

function DashboardPage() {
  const { config } = useAppConfig();
  const params = useParams();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const initialJobId = params.jobId || searchParams.get("job") || undefined;

  if (!config.apiKey) {
    return <AuthPrompt />;
  }

  return (
    <Dashboard
      initialJobId={initialJobId}
      onNavigateToJob={(jobId) => navigate(`/jobs/${jobId}`)}
    />
  );
}

export default function App() {
  return (
    <AppConfigProvider>
      <AppRoutes />
    </AppConfigProvider>
  );
}
