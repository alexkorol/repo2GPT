import { useLocation, Link } from "react-router-dom";
import { useAppConfig } from "../context/AppConfigContext";

interface HeaderBarProps {
  onOpenSettings: () => void;
}

export function HeaderBar({ onOpenSettings }: HeaderBarProps) {
  const { config } = useAppConfig();
  const location = useLocation();
  const jobId = location.pathname.startsWith("/jobs/")
    ? location.pathname.split("/jobs/")[1]
    : undefined;

  return (
    <header className="app-header">
      <div className="header-content">
        <Link to="/" className="brand">
          repo2GPT Control Panel
        </Link>
        <div className="header-meta">
          <span className="endpoint">API: {config.apiBaseUrl}</span>
          {jobId ? <span className="job-tag">Job {jobId}</span> : null}
        </div>
      </div>
      <div className="header-actions">
        <button type="button" className="btn" onClick={onOpenSettings}>
          Settings
        </button>
      </div>
    </header>
  );
}
