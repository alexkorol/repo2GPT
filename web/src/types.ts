export type JobStatus = "pending" | "running" | "completed" | "failed";

export interface JobResponse {
  id: string;
  status: JobStatus;
  created_at: string;
  updated_at: string;
}

export interface JobResult {
  repomap_path: string;
  chunks: Array<{
    index: number;
    token_count: number;
    file_count: number;
    path: string;
  }>;
  warnings?: string[];
  token_estimator?: {
    enabled: boolean;
    strategy: string;
  };
  token_totals?: {
    chunk_tokens: number;
    repo_map_tokens: number;
    chunk_count: number;
  };
}

export interface JobRecord extends JobResponse {
  request: Record<string, unknown>;
  events: JobEvent[];
  result?: JobResult;
  error?: string | null;
}

export interface JobEvent {
  id: number;
  timestamp: string;
  event: string;
  message?: string | null;
  data: Record<string, unknown>;
}

export interface ArtifactChunk {
  index: number;
  token_count: number;
  file_count: number;
  content: string;
}

export interface JobArtifacts {
  repomap: string;
  chunks: ArtifactChunk[];
  warnings: string[];
  token_estimator?: {
    enabled: boolean;
    strategy: string;
  } | null;
  token_totals?: {
    chunk_tokens: number;
    repo_map_tokens: number;
    chunk_count: number;
  } | null;
}

export type SourceType = "git" | "archive_url" | "archive_upload";

export interface GitSourcePayload {
  type: "git";
  url: string;
  ref?: string;
}

export interface ArchiveUrlSourcePayload {
  type: "archive_url";
  url: string;
  filename?: string;
}

export interface ArchiveUploadSourcePayload {
  type: "archive_upload";
  filename: string;
  content_base64: string;
}

export type JobSourcePayload =
  | GitSourcePayload
  | ArchiveUrlSourcePayload
  | ArchiveUploadSourcePayload;

export interface ProcessingOptionsPayload {
  ignore_patterns?: string[];
  include_patterns?: string[];
  allowed_extensions?: string[];
  special_filenames?: string[];
  max_file_bytes?: number | null;
  allow_non_code?: boolean;
}

export interface JobCreatePayload {
  source: JobSourcePayload;
  options?: ProcessingOptionsPayload;
  chunk_token_limit?: number | null;
  enable_token_counts?: boolean;
}
