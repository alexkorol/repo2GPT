import { JobArtifacts, JobCreatePayload, JobRecord, JobResponse } from "../types";

export interface ApiConfig {
  apiBaseUrl: string;
  apiKey: string;
}

async function request<T>(
  path: string,
  config: ApiConfig,
  init?: RequestInit
): Promise<T> {
  const headers = new Headers(init?.headers);
  headers.set("Accept", "application/json");
  if (config.apiKey) {
    headers.set("X-API-Key", config.apiKey);
  }
  const response = await fetch(`${config.apiBaseUrl}${path}`, {
    ...init,
    headers,
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(
      `Request failed with status ${response.status}: ${text || response.statusText}`
    );
  }
  if (response.status === 204) {
    return undefined as T;
  }
  const data = (await response.json()) as T;
  return data;
}

export async function createJob(
  payload: JobCreatePayload,
  config: ApiConfig
): Promise<JobResponse> {
  return request<JobResponse>("/jobs", config, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
}

export async function getJob(jobId: string, config: ApiConfig): Promise<JobRecord> {
  return request<JobRecord>(`/jobs/${jobId}`, config);
}

export async function getJobArtifacts(
  jobId: string,
  config: ApiConfig
): Promise<JobArtifacts> {
  return request<JobArtifacts>(`/jobs/${jobId}/artifacts`, config);
}

export async function streamJobEvents(
  jobId: string,
  config: ApiConfig,
  signal: AbortSignal,
  onEvent: (event: MessageEvent<Record<string, unknown>>) => void,
  onError: (error: Error) => void
): Promise<void> {
  try {
    const response = await fetch(`${config.apiBaseUrl}/jobs/${jobId}/events`, {
      headers: config.apiKey ? { "X-API-Key": config.apiKey } : undefined,
      signal,
    });
    if (!response.ok || !response.body) {
      throw new Error(`Unable to open event stream (${response.status})`);
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (!signal.aborted) {
      const { done, value } = await reader.read();
      if (done) {
        break;
      }
      buffer += decoder.decode(value, { stream: true });
      let separatorIndex = buffer.indexOf("\n\n");
      while (separatorIndex >= 0) {
        const rawEvent = buffer.slice(0, separatorIndex);
        buffer = buffer.slice(separatorIndex + 2);
        const parsed = parseSseEvent(rawEvent);
        if (parsed) {
          onEvent(parsed);
        }
        separatorIndex = buffer.indexOf("\n\n");
      }
    }
  } catch (error) {
    if (signal.aborted) {
      return;
    }
    onError(error instanceof Error ? error : new Error(String(error)));
  }
}

interface ParsedEvent {
  id?: number;
  event: string;
  data: Record<string, unknown>;
  message?: string | null;
  timestamp?: string;
}

function parseSseEvent(raw: string): MessageEvent<Record<string, unknown>> | null {
  if (!raw.trim()) {
    return null;
  }
  const lines = raw.split("\n");
  let eventName = "message";
  let id: number | undefined;
  const dataLines: string[] = [];
  for (const line of lines) {
    if (line.startsWith(":")) {
      continue;
    }
    const [field, ...rest] = line.split(":");
    const value = rest.join(":").trim();
    switch (field) {
      case "event":
        eventName = value || "message";
        break;
      case "id":
        id = value ? Number(value) : undefined;
        break;
      case "data":
        dataLines.push(value);
        break;
    }
  }
  const dataText = dataLines.join("\n");
  let data: Record<string, unknown> = {};
  if (dataText) {
    try {
      data = JSON.parse(dataText);
    } catch (error) {
      console.warn("Failed to parse SSE payload", error);
    }
  }
  const event: ParsedEvent = {
    id,
    event: eventName,
    data,
  };
  return new MessageEvent<Record<string, unknown>>(eventName, {
    data: event.data,
    lastEventId: event.id?.toString(),
  });
}
