import { FormEvent, useEffect, useState } from "react";
import { useAppConfig } from "../context/AppConfigContext";

interface SettingsPanelProps {
  open: boolean;
  onClose: () => void;
}

export function SettingsPanel({ open, onClose }: SettingsPanelProps) {
  const { config, setApiBaseUrl, setApiKey, setGeminiApiKey, resetCredentials } =
    useAppConfig();
  const [localBaseUrl, setLocalBaseUrl] = useState(config.apiBaseUrl);
  const [localApiKey, setLocalApiKey] = useState(config.apiKey);
  const [localGeminiKey, setLocalGeminiKey] = useState(config.geminiApiKey);
  const [status, setStatus] = useState<string | null>(null);
  const [testing, setTesting] = useState(false);

  useEffect(() => {
    if (open) {
      setLocalBaseUrl(config.apiBaseUrl);
      setLocalApiKey(config.apiKey);
      setLocalGeminiKey(config.geminiApiKey);
      setStatus(null);
    }
  }, [open, config]);

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setApiBaseUrl(localBaseUrl.trim());
    setApiKey(localApiKey.trim());
    setGeminiApiKey(localGeminiKey.trim());
    onClose();
  };

  const handleTestConnection = async () => {
    setTesting(true);
    setStatus(null);
    try {
      const response = await fetch(`${localBaseUrl.replace(/\/$/, "")}/healthz`);
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      setStatus("API is reachable");
    } catch (error) {
      setStatus(`Connection failed: ${error}`);
    } finally {
      setTesting(false);
    }
  };

  if (!open) {
    return null;
  }

  return (
    <div className="settings-backdrop" role="dialog" aria-modal="true">
      <div className="settings-panel">
        <div className="settings-header">
          <h2>Connection settings</h2>
          <button className="btn btn-link" onClick={onClose}>
            Close
          </button>
        </div>
        <form className="settings-form" onSubmit={handleSubmit}>
          <label className="field">
            <span>API base URL</span>
            <input
              type="url"
              value={localBaseUrl}
              onChange={(event) => setLocalBaseUrl(event.target.value)}
              placeholder="http://localhost:8000"
              required
            />
          </label>
          <label className="field">
            <span>API token</span>
            <input
              type="password"
              value={localApiKey}
              onChange={(event) => setLocalApiKey(event.target.value)}
              placeholder="Paste API key"
              required
            />
          </label>
          <label className="field">
            <span>Gemini access token (optional)</span>
            <input
              type="password"
              value={localGeminiKey}
              onChange={(event) => setLocalGeminiKey(event.target.value)}
              placeholder="ya29..."
            />
            <small>
              Stored locally and used to upload artifacts via the Google AI File
              API.
            </small>
          </label>
          <div className="settings-actions">
            <button
              className="btn btn-secondary"
              type="button"
              onClick={handleTestConnection}
              disabled={testing}
            >
              {testing ? "Testing..." : "Test connection"}
            </button>
            <button className="btn" type="submit">
              Save
            </button>
            <button
              className="btn btn-link"
              type="button"
              onClick={() => {
                resetCredentials();
                setLocalApiKey("");
                setLocalGeminiKey("");
              }}
            >
              Clear credentials
            </button>
          </div>
          {status ? <p className="settings-status">{status}</p> : null}
        </form>
      </div>
    </div>
  );
}
