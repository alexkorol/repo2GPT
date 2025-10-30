import { useState } from "react";
import { useAppConfig } from "../context/AppConfigContext";
import { JobArtifacts } from "../types";
import { createArtifactArchive } from "../utils/artifacts";

interface GeminiUploaderProps {
  jobId: string;
  artifacts?: JobArtifacts;
}

export function GeminiUploader({ jobId, artifacts }: GeminiUploaderProps) {
  const { config } = useAppConfig();
  const [status, setStatus] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);

  if (!artifacts) {
    return null;
  }

  const handleUpload = async () => {
    if (!config.geminiApiKey) {
      setStatus("Configure a Gemini access token in settings first.");
      return;
    }
    setUploading(true);
    setStatus(null);
    try {
      const bundle = await createArtifactArchive(jobId, artifacts);
      const response = await fetch(
        `https://generativelanguage.googleapis.com/upload/v1beta/files?key=${encodeURIComponent(
          config.geminiApiKey
        )}`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/zip",
            "X-Goog-Upload-File-Name": `${jobId}.zip`,
            "X-Goog-Upload-Protocol": "raw",
          },
          body: bundle,
        }
      );
      if (!response.ok) {
        const text = await response.text();
        throw new Error(`Upload failed (${response.status}): ${text}`);
      }
      const json = await response.json();
      setStatus(`Uploaded as ${json.name || "file"}`);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="gemini-uploader">
      <button className="btn btn-secondary" onClick={handleUpload} disabled={uploading}>
        {uploading ? "Uploading to Gemini..." : "Upload bundle to Gemini"}
      </button>
      {status ? <p className="muted">{status}</p> : null}
    </div>
  );
}
