/**
 * services/testsApi.service.ts
 * ---------------------------------------------------------------------------
 * Real HTTP client for the Test Generation endpoints (Feature 1) + the two
 * existing UPM endpoints the form needs (versions, tree).
 *
 * Switch between real back-end and simulated data with ONE env variable:
 *     VITE_TESTS_MOCK=true   -> mock (no back-end needed)
 *     VITE_TESTS_MOCK=false  -> real back-end
 *
 * All methods throw `ApiProblem` (status + code + message), never raw axios errors.
 */
import axios, { type AxiosResponse } from 'axios';
import apiClient from './apiClient';
import { mockTestsApi } from './testsMock.service';
import { forgetRun, readLocalRuns, rememberRun } from './testsHistory.service';
import {
  ApiProblem,
  type CoverageResponse,
  type CreateJobRequest,
  type CreateJobResponse,
  type JobDetail,
  type JobHistory,
  type JobStatus,
  type JobSummary,
  type PlanResponse,
  type RecordsFilter,
  type RecordsResponse,
  type TestsApi,
  type TreeResponse,
  type VersionsResponse,
} from '../types/tests';

export const USE_TESTS_MOCK: boolean = String(import.meta.env.VITE_TESTS_MOCK ?? 'false') === 'true';

const JOBS = '/api/analysis/tests/jobs/';
const jobUrl = (jobId: string, suffix = '') => `${JOBS}${encodeURIComponent(jobId)}/${suffix}`;

// ── error normalization ─────────────────────────────────────────────────────
const codeFromStatus = (status: number): string => {
  switch (status) {
    case 400: return 'validation_error';
    case 401: return 'unauthorized';
    case 403: return 'forbidden';
    case 404: return 'not_found';
    case 409: return 'conflict';
    case 422: return 'unprocessable';
    default:  return 'unknown';
  }
};

/** The exact error body is not fixed yet, so several shapes are accepted. */
const extractCode = (data: unknown): string | undefined => {
  if (!data || typeof data !== 'object') return undefined;
  const d = data as Record<string, unknown>;
  if (typeof d.error === 'string') return d.error;
  if (d.error && typeof d.error === 'object') {
    const c = (d.error as Record<string, unknown>).code;
    if (typeof c === 'string') return c;
  }
  if (typeof d.code === 'string') return d.code;
  return undefined;
};

const extractMessage = (data: unknown): string | undefined => {
  if (!data || typeof data !== 'object') return undefined;
  const d = data as Record<string, unknown>;
  if (typeof d.message === 'string') return d.message;
  if (typeof d.detail === 'string') return d.detail;
  if (d.error && typeof d.error === 'object') {
    const m = (d.error as Record<string, unknown>).message;
    if (typeof m === 'string') return m;
  }
  return undefined;
};

export const toProblem = (err: unknown): ApiProblem => {
  if (err instanceof ApiProblem) return err;
  if (axios.isAxiosError(err)) {
    if (!err.response) return new ApiProblem(0, 'network', err.message || 'Network error');
    const { status, data } = err.response;
    const code = extractCode(data) ?? codeFromStatus(status);
    return new ApiProblem(status, code, extractMessage(data) ?? err.message);
  }
  return new ApiProblem(0, 'unknown', err instanceof Error ? err.message : 'Unknown error');
};

async function call<T>(fn: () => Promise<AxiosResponse<T>>): Promise<T> {
  try {
    return (await fn()).data;
  } catch (e) {
    throw toProblem(e);
  }
}

// ── run history helpers ─────────────────────────────────────────────────────
const MAX_LOCAL_LOOKUPS = 15;
const byNewest = (a: JobSummary, b: JobSummary) => (b.created_at ?? '').localeCompare(a.created_at ?? '');

/** Accepts the likely shapes of a server list item; returns null when it is unusable. */
const toSummary = (raw: unknown, fallbackProject: string): JobSummary | null => {
  if (!raw || typeof raw !== 'object') return null;
  const r = raw as Record<string, unknown>;
  const id = (r.job_id ?? r.id) as unknown;
  if (typeof id !== 'string') return null;
  const created = (r.created_at ?? r.started_at ?? null) as unknown;
  return {
    job_id: id,
    project_id: typeof r.project_id === 'string' ? r.project_id : fallbackProject,
    version_number: Number(r.version_number ?? 0),
    status: typeof r.status === 'string' ? r.status : 'pending',
    created_at: typeof created === 'string' ? created : null,
    progress: r.progress && typeof r.progress === 'object' ? (r.progress as JobSummary['progress']) : undefined,
  };
};

// ── real implementation ─────────────────────────────────────────────────────
const realTestsApi: TestsApi = {
  /**
   * Preferred: the server list (proposal, not in the approved plan yet).
   * If the endpoint does not exist (404/405/501) fall back to the runs this browser remembers.
   */
  async listJobs(projectId: string): Promise<JobHistory> {
    try {
      const data = await call<unknown>(() => apiClient.get(JOBS, { params: { project_id: projectId } }));
      const d = data as { items?: unknown[]; results?: unknown[] } | unknown[];
      const arr = Array.isArray(d) ? d : d?.items ?? d?.results ?? [];
      const items = arr.map((x) => toSummary(x, projectId)).filter((x): x is JobSummary => x !== null);
      return { items: items.sort(byNewest), source: 'server' };
    } catch (e) {
      const p = toProblem(e);
      if (![404, 405, 501].includes(p.status)) throw p;
    }

    const local = readLocalRuns(projectId).slice(0, MAX_LOCAL_LOOKUPS);
    const settled = await Promise.allSettled(local.map((r) => call<JobDetail>(() => apiClient.get(jobUrl(r.job_id)))));
    const items: JobSummary[] = [];
    settled.forEach((res, i) => {
      const run = local[i];
      if (res.status === 'fulfilled') {
        items.push({
          job_id: run.job_id,
          project_id: projectId,
          version_number: res.value.version_number ?? run.version_number,
          status: res.value.status,
          created_at: run.created_at,
          progress: res.value.progress,
        });
      } else if (toProblem(res.reason).status === 404) {
        forgetRun(projectId, run.job_id); // the job no longer exists on the server
      } else {
        items.push({ job_id: run.job_id, project_id: projectId, version_number: run.version_number, status: 'unknown', created_at: run.created_at });
      }
    });
    return { items: items.sort(byNewest), source: 'local' };
  },

  // Existing endpoint (UPM proxy -> AI service). Used for the version dropdown.
  getVersions: (projectId: string) =>
    call<VersionsResponse>(() => apiClient.get(`/api/upm/projects/${encodeURIComponent(projectId)}/versions/`)),

  // Existing endpoint. `flat_files[].filepath` is what goes into `paths[]`.
  getTree: (projectId: string, version: number) =>
    call<TreeResponse>(() =>
      apiClient.get(`/api/upm/projects/${encodeURIComponent(projectId)}/tree/`, { params: { version } }),
    ),

  async createJob(body: CreateJobRequest) {
    const res = await call<CreateJobResponse>(() => apiClient.post(JOBS, body));
    // remember it for the "Tested" list (fallback when the server has no list endpoint)
    rememberRun(body.project_id, { job_id: res.job_id, version_number: res.version_number, created_at: new Date().toISOString() });
    return res;
  },

  getJob: (jobId: string) => call<JobDetail>(() => apiClient.get(jobUrl(jobId))),

  getPlan: (jobId: string) => call<PlanResponse>(() => apiClient.get(jobUrl(jobId, 'plan/'))),

  getRecords: (jobId: string, filter: RecordsFilter = {}) => {
    const params: Record<string, string> = {};
    if (filter.status) params.status = filter.status;
    if (filter.level) params.level = filter.level;
    if (filter.path) params.path = filter.path;
    return call<RecordsResponse>(() => apiClient.get(jobUrl(jobId, 'records/'), { params }));
  },

  getCoverage: (jobId: string) => call<CoverageResponse>(() => apiClient.get(jobUrl(jobId, 'coverage/'))),

  cancelJob: (jobId: string) =>
    call<{ job_id: string; status: JobStatus }>(() => apiClient.post(jobUrl(jobId, 'cancel/'))),

  async downloadZip(jobId: string) {
    try {
      const res = await apiClient.get(jobUrl(jobId, 'download/'), { responseType: 'blob' });
      const disposition: string = res.headers['content-disposition'] ?? '';
      const match = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(disposition);
      return { blob: res.data as Blob, filename: match ? decodeURIComponent(match[1]) : `tests_${jobId}.zip` };
    } catch (e) {
      // With responseType 'blob' an error body (e.g. 409 no_ready_tests) arrives as a Blob: decode it.
      if (axios.isAxiosError(e) && e.response?.data instanceof Blob) {
        try {
          e.response.data = JSON.parse(await e.response.data.text());
        } catch {
          /* body was not JSON: fall back to the status code */
        }
      }
      throw toProblem(e);
    }
  },
};

/** The one object the UI imports. Real or mock, decided by VITE_TESTS_MOCK. */
export const testsApi: TestsApi = USE_TESTS_MOCK ? mockTestsApi : realTestsApi;

/** Saves a Blob as a file in the browser. */
export const saveBlob = (blob: Blob, filename: string): void => {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
};