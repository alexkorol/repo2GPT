import { useEffect, useMemo, useState } from "react";
import {
  JobArtifacts,
  JobCreatePayload,
  JobEvent,
  JobRecord,
  JobResponse,
  JobStatus,
} from "../types";
import {
  ApiConfig,
  createJob,
  getJob,
  getJobArtifacts,
  streamJobEvents,
} from "../api/client";
import { useAppConfig } from "../context/AppConfigContext";
import { JobForm } from "./JobForm";
import { JobMonitor } from "./JobMonitor";

interface DashboardProps {
  initialJobId?: string;
  onNavigateToJob: (jobId: string) => void;
}

interface JobState {
  meta?: JobRecord;
  events: JobEvent[];
  artifacts?: JobArtifacts;
  status?: JobStatus;
  loading: boolean;
  error?: string | null;
  eventError?: string | null;
}

export function Dashboard({ initialJobId, onNavigateToJob }: DashboardProps) {
  const { config } = useAppConfig();
  const [jobId, setJobId] = useState<string | undefined>(initialJobId);
  const [jobState, setJobState] = useState<JobState>({
    events: [],
    loading: false,
  });

  useEffect(() => {
    setJobId(initialJobId);
  }, [initialJobId]);

  const apiConfig = useMemo<ApiConfig>(() => ({
    apiBaseUrl: config.apiBaseUrl,
    apiKey: config.apiKey,
  }), [config.apiBaseUrl, config.apiKey]);

  useEffect(() => {
    if (!jobId) {
      return;
    }
    let cancelled = false;
    setJobState((state) => ({ ...state, loading: true, error: null }));
    (async () => {
      try {
        const record = await getJob(jobId, apiConfig);
        if (cancelled) {
          return;
        }
        const events = (record.events || []).map(normalizeEvent);
        setJobState((state) => ({
          ...state,
          meta: record,
          status: record.status,
          events,
          loading: false,
        }));
        if (record.status === "completed") {
          const artifacts = await getJobArtifacts(jobId, apiConfig);
          if (!cancelled) {
            setJobState((state) => ({ ...state, artifacts }));
          }
        }
      } catch (error) {
        if (!cancelled) {
          setJobState((state) => ({
            ...state,
            loading: false,
            error: error instanceof Error ? error.message : String(error),
          }));
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [jobId, apiConfig]);

  useEffect(() => {
    if (!jobId) {
      return;
    }
    const controller = new AbortController();
    streamJobEvents(
      jobId,
      apiConfig,
      controller.signal,
      (event) => {
        const payload = event.data as Record<string, unknown>;
        const normalized = normalizeEvent(payload);
        if (!normalized.id) {
          return;
        }
        setJobState((state) => {
          const nextEvents = new Map<number, JobEvent>();
          state.events.forEach((existing) =>
            nextEvents.set(existing.id, existing)
          );
          nextEvents.set(normalized.id, normalized);
          const events = Array.from(nextEvents.values()).sort(
            (a, b) => a.id - b.id
          );
          const statusUpdate =
            normalized.event === "status"
              ? (normalized.data.status as JobStatus | undefined)
              : undefined;
          const updatedMeta = state.meta
            ? {
                ...state.meta,
                status: statusUpdate || state.meta.status,
                updated_at: normalized.timestamp || state.meta.updated_at,
              }
            : state.meta;
          return {
            ...state,
            events,
            status: statusUpdate || state.status,
            meta: updatedMeta,
            eventError: null,
          };
        });
        if (
          normalized.event === "status" &&
          (normalized.data.status === "completed" ||
            normalized.data.status === "failed")
        ) {
          if (normalized.data.status === "completed") {
            getJobArtifacts(jobId, apiConfig)
              .then((artifacts) => {
                setJobState((state) => ({ ...state, artifacts }));
              })
              .catch((error) => {
                setJobState((state) => ({
                  ...state,
                  eventError: error instanceof Error ? error.message : String(error),
                }));
              });
          }
        }
      },
      (error) =>
        setJobState((state) => ({
          ...state,
          eventError: error.message,
        }))
    ).catch((error) => {
      if (controller.signal.aborted) {
        return;
      }
      setJobState((state) => ({
        ...state,
        eventError: error instanceof Error ? error.message : String(error),
      }));
    });
    return () => {
      controller.abort();
    };
  }, [jobId, apiConfig]);

  const handleJobCreated = (response: JobResponse) => {
    setJobId(response.id);
    setJobState({
      meta: undefined,
      events: [],
      artifacts: undefined,
      status: response.status,
      loading: false,
      error: null,
      eventError: null,
    });
    onNavigateToJob(response.id);
  };

  const handleSubmitJob = async (payload: JobCreatePayload) => {
    const response = await createJob(payload, apiConfig);
    handleJobCreated(response);
    return response;
  };

  return (
    <div className="dashboard">
      <section className="panel panel-form">
        <JobForm onSubmit={handleSubmitJob} busy={jobState.loading && !!jobId} />
      </section>
      <section className="panel panel-monitor">
        <JobMonitor
          jobId={jobId}
          jobState={jobState}
          onRefresh={async () => {
            if (!jobId) return;
            setJobState((state) => ({ ...state, loading: true }));
            try {
              const record = await getJob(jobId, apiConfig);
              const events = (record.events || []).map(normalizeEvent);
              let artifacts: JobArtifacts | undefined;
              if (record.status === "completed") {
                artifacts = await getJobArtifacts(jobId, apiConfig);
              }
              setJobState((state) => ({
                ...state,
                meta: record,
                status: record.status,
                events,
                artifacts: artifacts ?? state.artifacts,
                loading: false,
                error: null,
              }));
            } catch (error) {
              setJobState((state) => ({
                ...state,
                loading: false,
                error: error instanceof Error ? error.message : String(error),
              }));
            }
          }}
        />
      </section>
    </div>
  );
}

function normalizeEvent(raw: unknown): JobEvent {
  const event = (raw ?? {}) as Record<string, unknown>;
  return {
    id: Number(event.id ?? 0),
    timestamp: String(event.timestamp ?? ""),
    event: String(event.event ?? "message"),
    message: (event.message as string | undefined) || null,
    data: (event.data as Record<string, unknown>) || {},
  };
}
