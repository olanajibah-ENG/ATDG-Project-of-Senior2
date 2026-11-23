/**
 * types/tests.ts
 * ---------------------------------------------------------------------------
 * Types for the Test Generation feature (Feature 1).
 * They follow the approved back-end plan "Feature1_Postman_API_Graphify_SpecKit.pdf":
 *   POST /api/analysis/tests/jobs/            -> start a job
 *   GET  /api/analysis/tests/jobs/{id}/       -> status + progress (poll ~2s)
 *   GET  .../plan/  .../records/  .../coverage/  .../download/   POST .../cancel/
 *
 * Fields marked "OPEN" are not fixed yet by the back-end developer
 * (stage values, error shape, reason codes). The UI treats them as free
 * strings and falls back to a humanized label, so a new value never breaks it.
 */

export type TestLevel = 'unit' | 'edge' | 'integration';
export const ALL_LEVELS: TestLevel[] = ['unit', 'edge', 'integration'];

export type JobStatus =
  | 'pending'
  | 'running'
  | 'completed'
  | 'completed_with_issues'
  | 'failed'
  | 'cancelled';

export const TERMINAL_JOB_STATUSES: JobStatus[] = [
  'completed',
  'completed_with_issues',
  'failed',
  'cancelled',
];

export const isTerminalJob = (status: string): boolean =>
  (TERMINAL_JOB_STATUSES as string[]).includes(status);

/** Status of one file inside a job. */
export type FileStatus = 'pending' | 'ready' | 'partial' | 'failed' | 'skipped';

/** Status of one test record (unit x level). */
export type RecordStatus =
  | 'pending'
  | 'ready'
  | 'generation_failed'
  | 'environment_error'
  | 'test_failed'
  | 'skipped';

// ── POST /jobs/ ─────────────────────────────────────────────────────────────
export interface CreateJobRequest {
  /** UPM project UUID (string). NOT an integer. */
  project_id: string;
  /** Optional: omitted = latest version. */
  version_number?: number;
  /** filepath values from the tree. Empty array = all files of the version. */
  paths: string[];
  /** Optional: omitted = all three levels. */
  levels: TestLevel[];
}

export interface CreateJobResponse {
  job_id: string;
  status: JobStatus;
  project_id: string;
  version_number: number;
}

// ── GET /jobs/{id}/ ─────────────────────────────────────────────────────────
export interface JobProgress {
  total: number;
  done: number;
  by_status: Partial<Record<RecordStatus, number>>;
}

export interface JobFile {
  path: string;
  status: FileStatus;
  levels?: Partial<Record<TestLevel, RecordStatus>>;
  /** e.g. "unsupported_language" (OPEN list). */
  reason?: string | null;
}

/** OPEN: shape of `error` is not fixed yet. Both forms are handled. */
export type JobError = null | string | { code?: string; message?: string; [k: string]: unknown };

export interface JobDetail {
  job_id: string;
  project_id: string;
  version_number: number;
  status: JobStatus;
  /** OPEN: full list of stage values is not fixed yet. */
  stage?: string | null;
  progress: JobProgress;
  files: JobFile[];
  error: JobError;
}

// ── GET /jobs/{id}/plan/ ────────────────────────────────────────────────────
export interface PlanUnit {
  id: string;
  file: string;
  kind: string;
}
export interface PlanSkipped {
  path: string;
  reason: string;
}
export interface PlanResponse {
  units: PlanUnit[];
  skipped: PlanSkipped[];
  work_items_count: number;
}

// ── GET /jobs/{id}/records/ ─────────────────────────────────────────────────
export interface TestRecord {
  id: string;
  file: string;
  unit_id: string;
  level: TestLevel;
  status: RecordStatus;
  reason_code: string | null;
  test_path: string | null;
}
export interface RecordsResponse {
  items: TestRecord[];
  total: number;
}
export interface RecordsFilter {
  status?: RecordStatus | '';
  level?: TestLevel | '';
  path?: string;
}

// ── GET /jobs/{id}/coverage/ ────────────────────────────────────────────────
export interface CoverageFile {
  path: string;
  line_percent: number;
  branch_percent: number;
  missing_lines: number[];
}
export interface CoverageResponse {
  line_percent: number;
  branch_percent: number;
  files: CoverageFile[];
}

// ── Existing UPM endpoints used by the form ─────────────────────────────────
/** GET /api/upm/projects/{id}/versions/ */
export interface ProjectVersion {
  version_number: number;
  total_files: number;
  new_files?: number | null;
  unchanged_files?: number | null;
  created_at: string | null;
}
export interface VersionsResponse {
  project_id: string;
  project_name: string;
  versions: ProjectVersion[];
}

/** One entry of `flat_files` in GET /api/upm/projects/{id}/tree/?version=N */
export interface TreeFile {
  file_id: string;
  filename: string;
  filepath: string;
  file_type: string;
  status: 'new' | 'new_or_modified' | 'unchanged' | string;
}
export interface TreeResponse {
  project_id: string;
  project_name: string;
  version_number: number;
  flat_files: TreeFile[];
}

// ── Normalized error used everywhere in the UI ──────────────────────────────
export class ApiProblem extends Error {
  status: number;
  code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = 'ApiProblem';
    this.status = status;
    this.code = code;
  }
}

// ── Run history (list of earlier jobs of a project) ─────────────────────────
/**
 * NOT in the approved API. It needs `GET /api/analysis/tests/jobs/?project_id=<uuid>`
 * (proposal sent to the back-end developer). Until that exists the UI builds the
 * list from the job ids it remembered in this browser (source = 'local').
 */
export interface JobSummary {
  job_id: string;
  project_id: string;
  version_number: number;
  /** Kept as string so a new back-end status never breaks the list. */
  status: string;
  created_at: string | null;
  progress?: JobProgress;
}
export interface JobHistory {
  items: JobSummary[];
  /** 'server' = complete list from the back-end; 'local' = only runs started from this browser. */
  source: 'server' | 'local';
}

/** Contract implemented by both the real service and the mock service. */
export interface TestsApi {
  listJobs(projectId: string): Promise<JobHistory>;
  getVersions(projectId: string): Promise<VersionsResponse>;
  getTree(projectId: string, version: number): Promise<TreeResponse>;
  createJob(body: CreateJobRequest): Promise<CreateJobResponse>;
  getJob(jobId: string): Promise<JobDetail>;
  getPlan(jobId: string): Promise<PlanResponse>;
  getRecords(jobId: string, filter?: RecordsFilter): Promise<RecordsResponse>;
  getCoverage(jobId: string): Promise<CoverageResponse>;
  cancelJob(jobId: string): Promise<{ job_id: string; status: JobStatus }>;
  downloadZip(jobId: string): Promise<{ blob: Blob; filename: string }>;
}