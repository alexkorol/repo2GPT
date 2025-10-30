import { FormEvent, useMemo, useState } from "react";
import {
  ArchiveUploadSourcePayload,
  JobCreatePayload,
  JobResponse,
  SourceType,
} from "../types";

interface JobFormProps {
  onSubmit: (payload: JobCreatePayload) => Promise<JobResponse>;
  busy?: boolean;
}

interface UploadState extends ArchiveUploadSourcePayload {}

export function JobForm({ onSubmit, busy }: JobFormProps) {
  const [sourceType, setSourceType] = useState<SourceType>("git");
  const [gitUrl, setGitUrl] = useState("");
  const [gitRef, setGitRef] = useState("");
  const [archiveUrl, setArchiveUrl] = useState("");
  const [archiveFilename, setArchiveFilename] = useState("");
  const [upload, setUpload] = useState<UploadState | null>(null);
  const [ignorePatterns, setIgnorePatterns] = useState(".git\nnode_modules\n.env");
  const [includePatterns, setIncludePatterns] = useState("");
  const [allowedExtensions, setAllowedExtensions] = useState("");
  const [chunkLimit, setChunkLimit] = useState<number | undefined>(undefined);
  const [enableTokens, setEnableTokens] = useState(true);
  const [allowNonCode, setAllowNonCode] = useState(false);
  const [maxFileBytes, setMaxFileBytes] = useState<string>("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const options = useMemo(() => {
    const payload: JobCreatePayload["options"] = {};
    if (ignorePatterns.trim()) {
      payload.ignore_patterns = splitLines(ignorePatterns);
    }
    if (includePatterns.trim()) {
      payload.include_patterns = splitLines(includePatterns);
    }
    if (allowedExtensions.trim()) {
      payload.allowed_extensions = splitLines(allowedExtensions);
    }
    if (allowNonCode) {
      payload.allow_non_code = true;
    }
    if (maxFileBytes.trim()) {
      const numeric = Number(maxFileBytes);
      if (!Number.isNaN(numeric)) {
        payload.max_file_bytes = numeric;
      }
    }
    return payload;
  }, [ignorePatterns, includePatterns, allowedExtensions, allowNonCode, maxFileBytes]);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const payload: JobCreatePayload = {
        source: buildSourcePayload(sourceType, {
          gitUrl,
          gitRef,
          archiveUrl,
          archiveFilename,
          upload,
        }),
        enable_token_counts: enableTokens,
      };
      if (Object.keys(options).length > 0) {
        payload.options = options;
      }
      if (chunkLimit) {
        payload.chunk_token_limit = chunkLimit;
      }
      await onSubmit(payload);
    } catch (error) {
      setError(error instanceof Error ? error.message : String(error));
    } finally {
      setSubmitting(false);
    }
  };

  const onFileSelected = async (fileList: FileList | null) => {
    if (!fileList || fileList.length === 0) {
      setUpload(null);
      return;
    }
    const file = fileList[0];
    const reader = new FileReader();
    reader.onload = () => {
      const result = reader.result;
      if (typeof result === "string") {
        const base64 = result.split(",")[1] || "";
        setUpload({ type: "archive_upload", filename: file.name, content_base64: base64 });
      }
    };
    reader.onerror = () => {
      setError("Failed to read archive file");
    };
    reader.readAsDataURL(file);
  };

  return (
    <form className="job-form" onSubmit={handleSubmit}>
      <h2>Submit a repository snapshot job</h2>
      <p className="muted">
        Provide either a Git URL, a downloadable archive, or upload a local
        archive. Jobs run asynchronously and stream progress events.
      </p>

      <fieldset className="field-group">
        <legend>Source</legend>
        <div className="field">
          <label htmlFor="source-select">Source type</label>
          <select
            id="source-select"
            value={sourceType}
            onChange={(event) => setSourceType(event.target.value as SourceType)}
          >
            <option value="git">Git repository URL</option>
            <option value="archive_url">Archive download URL</option>
            <option value="archive_upload">Upload archive</option>
          </select>
        </div>

        {sourceType === "git" ? (
          <>
            <div className="field">
              <label>Repository URL</label>
              <input
                type="url"
                value={gitUrl}
                onChange={(event) => setGitUrl(event.target.value)}
                placeholder="https://github.com/org/repo.git"
                required
              />
            </div>
            <div className="field">
              <label>Git reference (branch, tag, commit)</label>
              <input
                type="text"
                value={gitRef}
                onChange={(event) => setGitRef(event.target.value)}
                placeholder="main"
              />
            </div>
          </>
        ) : null}

        {sourceType === "archive_url" ? (
          <>
            <div className="field">
              <label>Archive URL</label>
              <input
                type="url"
                value={archiveUrl}
                onChange={(event) => setArchiveUrl(event.target.value)}
                placeholder="https://example.com/archive.tar.gz"
                required
              />
            </div>
            <div className="field">
              <label>Save as filename (optional)</label>
              <input
                type="text"
                value={archiveFilename}
                onChange={(event) => setArchiveFilename(event.target.value)}
                placeholder="repo.tar.gz"
              />
            </div>
          </>
        ) : null}

        {sourceType === "archive_upload" ? (
          <div className="field">
            <label>Upload tar/zip archive</label>
            <input
              type="file"
              accept=".zip,.tar,.tar.gz,.tgz,.tar.bz2,.tbz,.tar.xz,.txz"
              onChange={(event) => onFileSelected(event.target.files)}
              required
            />
            {upload ? (
              <p className="muted">
                Ready to upload <strong>{upload.filename}</strong>
              </p>
            ) : null}
          </div>
        ) : null}
      </fieldset>

      <fieldset className="field-group">
        <legend>Processing options</legend>
        <div className="field">
          <label>Ignore patterns</label>
          <textarea
            value={ignorePatterns}
            onChange={(event) => setIgnorePatterns(event.target.value)}
            rows={4}
          />
          <small>Newline separated glob patterns.</small>
        </div>
        <div className="field">
          <label>Include patterns</label>
          <textarea
            value={includePatterns}
            onChange={(event) => setIncludePatterns(event.target.value)}
            rows={2}
          />
        </div>
        <div className="field">
          <label>Allowed extensions</label>
          <textarea
            value={allowedExtensions}
            onChange={(event) => setAllowedExtensions(event.target.value)}
            rows={2}
          />
        </div>
        <div className="field-inline">
          <label>
            <span>Chunk token limit</span>
            <input
              type="number"
              min={1}
              value={chunkLimit ?? ""}
              onChange={(event) =>
                setChunkLimit(
                  event.target.value ? Number(event.target.value) : undefined
                )
              }
              placeholder="e.g. 1200"
            />
          </label>
          <label>
            <span>Max file bytes</span>
            <input
              type="number"
              min={1}
              value={maxFileBytes}
              onChange={(event) => setMaxFileBytes(event.target.value)}
              placeholder="e.g. 200000"
            />
          </label>
        </div>
        <div className="checkboxes">
          <label>
            <input
              type="checkbox"
              checked={enableTokens}
              onChange={(event) => setEnableTokens(event.target.checked)}
            />
            Track token counts per chunk
          </label>
          <label>
            <input
              type="checkbox"
              checked={allowNonCode}
              onChange={(event) => setAllowNonCode(event.target.checked)}
            />
            Include non-code files
          </label>
        </div>
      </fieldset>

      {error ? <p className="error">{error}</p> : null}

      <div className="form-actions">
        <button className="btn" type="submit" disabled={busy || submitting}>
          {busy || submitting ? "Submitting..." : "Submit job"}
        </button>
      </div>
    </form>
  );
}

function splitLines(value: string): string[] {
  return value
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
}

function buildSourcePayload(
  sourceType: SourceType,
  fields: {
    gitUrl: string;
    gitRef: string;
    archiveUrl: string;
    archiveFilename: string;
    upload: UploadState | null;
  }
): JobCreatePayload["source"] {
  switch (sourceType) {
    case "git":
      if (!fields.gitUrl) {
        throw new Error("Repository URL is required");
      }
      return {
        type: "git",
        url: fields.gitUrl,
        ref: fields.gitRef || undefined,
      };
    case "archive_url":
      if (!fields.archiveUrl) {
        throw new Error("Archive URL is required");
      }
      return {
        type: "archive_url",
        url: fields.archiveUrl,
        filename: fields.archiveFilename || undefined,
      };
    case "archive_upload":
      if (!fields.upload) {
        throw new Error("Archive upload is required");
      }
      return fields.upload as ArchiveUploadSourcePayload;
    default:
      throw new Error(`Unsupported source type: ${sourceType}`);
  }
}
