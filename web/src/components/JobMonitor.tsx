import { useMemo, useState } from "react";
import { ArtifactPreview } from "./ArtifactPreview";
import { EventTimeline } from "./EventTimeline";
import { GeminiUploader } from "./GeminiUploader";
import { createArtifactArchive } from "../utils/artifacts";
import { JobArtifacts, JobEvent, JobRecord, JobStatus } from "../types";

interface JobMonitorProps {
  jobId?: string;
  jobState: {
    meta?: JobRecord;
    events: JobEvent[];
    artifacts?: JobArtifacts;
    status?: JobStatus;
    loading: boolean;
    error?: string | null;
    eventError?: string | null;
  };
  onRefresh: () => void | Promise<void>;
}

export function JobMonitor({ jobId, jobState, onRefresh }: JobMonitorProps) {
  const [copyStatus, setCopyStatus] = useState<string | null>(null);
  const [downloading, setDownloading] = useState(false);

  const shareLink = useMemo(() => {
    if (!jobId || typeof window === "undefined") {
      return "";
    }
    return `${window.location.origin}/jobs/${jobId}`;
  }, [jobId]);

  if (!jobId) {
    return (
      <div className="job-monitor empty">
        <p>Select or submit a job to monitor progress and view artifacts.</p>
      </div>
    );
  }

  const handleCopyShareLink = async () => {
    if (!shareLink) {
      return;
    }
    try {
      await navigator.clipboard.writeText(shareLink);
      setCopyStatus("Copied!");
      setTimeout(() => setCopyStatus(null), 2000);
    } catch (error) {
      setCopyStatus("Copy failed");
    }
  };

  const handleDownloadArtifacts = async () => {
    if (!jobState.artifacts) {
      return;
    }
    setDownloading(true);
    try {
      const archive = await createArtifactArchive(jobId, jobState.artifacts);
      const url = URL.createObjectURL(archive);
      const link = document.createElement("a");
      link.href = url;
      link.download = `${jobId}_artifacts.zip`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
    } finally {
      setDownloading(false);
    }
  };

  return (
    <div className="job-monitor">
      <header className="job-header">
        <div>
          <h2>Job {jobId}</h2>
          <p>Status: <strong>{jobState.status ?? jobState.meta?.status}</strong></p>
          {jobState.meta ? (
            <p className="muted">
              Created {formatDate(jobState.meta.created_at)} · Last update {formatDate(jobState.meta.updated_at)}
            </p>
          ) : null}
        </div>
        <div className="job-actions">
          <button className="btn btn-secondary" onClick={handleCopyShareLink}>
            Copy shareable link
          </button>
          <button
            className="btn btn-secondary"
            onClick={handleDownloadArtifacts}
            disabled={!jobState.artifacts || downloading}
          >
            {downloading ? "Preparing download..." : "Download bundle"}
          </button>
          <button className="btn" onClick={() => onRefresh()} disabled={jobState.loading}>
            {jobState.loading ? "Refreshing..." : "Refresh"}
          </button>
        </div>
      </header>

      {copyStatus ? <p className="muted">{copyStatus}</p> : null}
      {jobState.error ? <p className="error">{jobState.error}</p> : null}
      {jobState.eventError ? <p className="error">{jobState.eventError}</p> : null}

      <section>
        <h3>Progress events</h3>
        <EventTimeline events={jobState.events} />
      </section>

      {jobState.artifacts ? (
        <section>
          <h3>Artifacts</h3>
          <ArtifactPreview jobId={jobId} artifacts={jobState.artifacts} />
          <GeminiUploader jobId={jobId} artifacts={jobState.artifacts} />
        </section>
      ) : (
        <p className="muted">
          Artifacts become available once the job completes successfully.
        </p>
      )}
    </div>
  );
}

function formatDate(value?: string) {
  if (!value) {
    return "";
  }
  const date = new Date(value);
  return `${date.toLocaleDateString()} ${date.toLocaleTimeString()}`;
}
