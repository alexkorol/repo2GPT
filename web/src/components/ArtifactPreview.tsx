import { useState } from "react";
import { JobArtifacts } from "../types";

interface ArtifactPreviewProps {
  jobId: string;
  artifacts: JobArtifacts;
}

export function ArtifactPreview({ jobId, artifacts }: ArtifactPreviewProps) {
  const [expandedChunk, setExpandedChunk] = useState<number | null>(null);

  return (
    <div className="artifact-preview">
      <section>
        <h3>Repository map</h3>
        <textarea value={artifacts.repomap} readOnly rows={12} />
      </section>
      <section>
        <h3>Token summary</h3>
        {artifacts.token_totals ? (
          <dl className="token-summary">
            <div>
              <dt>Total chunk tokens</dt>
              <dd>{artifacts.token_totals.chunk_tokens.toLocaleString()}</dd>
            </div>
            <div>
              <dt>Repo map tokens</dt>
              <dd>{artifacts.token_totals.repo_map_tokens.toLocaleString()}</dd>
            </div>
            <div>
              <dt>Chunk count</dt>
              <dd>{artifacts.token_totals.chunk_count}</dd>
            </div>
          </dl>
        ) : (
          <p className="muted">Token counting disabled for this run.</p>
        )}
      </section>
      <section>
        <h3>Chunks</h3>
        <div className="chunk-list">
          {artifacts.chunks.map((chunk) => {
            const expanded = expandedChunk === chunk.index;
            return (
              <details
                key={chunk.index}
                open={expanded}
                onToggle={(event) => {
                  if ((event.target as HTMLDetailsElement).open) {
                    setExpandedChunk(chunk.index);
                  } else {
                    setExpandedChunk(null);
                  }
                }}
              >
                <summary>
                  Chunk {chunk.index} · {chunk.token_count} tokens · {chunk.file_count} files
                </summary>
                <pre>{chunk.content}</pre>
              </details>
            );
          })}
        </div>
      </section>
      {artifacts.warnings && artifacts.warnings.length ? (
        <section>
          <h3>Warnings</h3>
          <ul>
            {artifacts.warnings.map((warning, index) => (
              <li key={`${jobId}-warning-${index}`}>{warning}</li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}
