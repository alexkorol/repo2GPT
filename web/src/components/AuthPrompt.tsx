import { useState } from "react";
import { SettingsPanel } from "./SettingsPanel";

export function AuthPrompt() {
  const [open, setOpen] = useState(true);

  return (
    <div className="auth-prompt">
      <h1>Connect to your repo2GPT API</h1>
      <p>
        Provide the shared API token configured for the FastAPI service to keep
        private repositories secure. Credentials are stored in your browser only
        and reused for subsequent sessions.
      </p>
      <button className="btn" onClick={() => setOpen(true)}>
        Configure connection
      </button>
      <SettingsPanel open={open} onClose={() => setOpen(false)} />
    </div>
  );
}
