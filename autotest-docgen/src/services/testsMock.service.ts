/**
 * services/testsMock.service.ts
 * ---------------------------------------------------------------------------
 * In-memory simulation of the Feature 1 back-end so the whole UI can be used
 * and reviewed BEFORE the real API exists. Active when VITE_TESTS_MOCK=true.
 *
 * The simulated job moves through: pending -> running (checking_analysis,
 * planning, generating, running_sandbox, accepting) -> completed_with_issues.
 * Stage names here are EXAMPLES: the real list is still open with the back-end.
 *
 * Hidden failure switch for testing error screens (browser console):
 *   localStorage.setItem('tests:mock:fail', 'analysis_missing')  // 409 on start
 *   localStorage.setItem('tests:mock:fail', 'forbidden')         // 403 on start
 *   localStorage.setItem('tests:mock:fail', 'network')           // network error
 *   localStorage.removeItem('tests:mock:fail')                   // back to normal
 *
 * Run-history switches (the "Tested" list):
 *   localStorage.setItem('tests:mock:fresh', '1')      // projects have NO earlier runs
 *   localStorage.setItem('tests:mock:history', 'local')// pretend the server has no list endpoint
 *   (by default every project starts with 2 earlier runs, to show the "tested before" flow)
 */
import {
  ApiProblem,
  isTerminalJob,
  type CoverageResponse,
  type CreateJobRequest,
  type CreateJobResponse,
  type FileStatus,
  type JobDetail,
  type JobFile,
  type JobHistory,
  type JobProgress,
  type JobStatus,
  type JobSummary,
  type PlanResponse,
  type ProjectVersion,
  type RecordStatus,
  type RecordsFilter,
  type RecordsResponse,
  type TestLevel,
  type TestRecord,
  type TestsApi,
  type TreeFile,
  type TreeResponse,
  type VersionsResponse,
} from '../types/tests';

const delay = (ms = 220) => new Promise<void>((r) => setTimeout(r, ms));

const PROJECT_NAME = 'MyTestProject';

const mkFile = (filepath: string, file_type: string, status: string): TreeFile => ({
  file_id: `f_${filepath}`,
  filename: filepath.split('/').pop() ?? filepath,
  filepath,
  file_type,
  status,
});

const ALL_FILES: TreeFile[] = [
  mkFile('MyTestProject/main.py', 'python', 'new_or_modified'),
  mkFile('MyTestProject/utils.py', 'python', 'unchanged'),
  mkFile('MyTestProject/models/student.py', 'python', 'new_or_modified'),
  mkFile('MyTestProject/models/course.py', 'python', 'unchanged'),
  mkFile('MyTestProject/services/enrollment.py', 'python', 'unchanged'),
  mkFile('MyTestProject/static/app.js', 'javascript', 'unchanged'),
  mkFile('MyTestProject/Legacy.java', 'java', 'unchanged'),
];

const VERSIONS: ProjectVersion[] = [
  { version_number: 3, total_files: 7, new_files: 2, unchanged_files: 5, created_at: '2026-11-12T10:30:00Z' },
  { version_number: 2, total_files: 6, new_files: 1, unchanged_files: 5, created_at: '2026-11-08T09:00:00Z' },
  { version_number: 1, total_files: 4, new_files: 4, unchanged_files: 0, created_at: '2026-11-03T08:00:00Z' },
];
const FILES_BY_VERSION: Record<number, number> = { 3: 7, 2: 6, 1: 4 };

const UNIT_NAMES: Record<string, string[]> = {
  'MyTestProject/main.py': ['main', 'run_cli', 'parse_args'],
  'MyTestProject/utils.py': ['slugify', 'clamp', 'read_config'],
  'MyTestProject/models/student.py': ['Student.__init__', 'Student.enroll', 'Student.gpa'],
  'MyTestProject/models/course.py': ['Course.add_student', 'Course.is_full'],
  'MyTestProject/services/enrollment.py': ['EnrollmentService.enroll', 'EnrollmentService.drop', 'validate_request'],
};

const hash = (s: string): number => {
  let x = 7;
  for (let i = 0; i < s.length; i++) x = (x * 31 + s.charCodeAt(i)) >>> 0;
  return x;
};

const isPython = (f: TreeFile) => f.file_type === 'python';
const toUnitId = (path: string, name: string) => `${path.replace(/\.py$/, '').replace(/\//g, '.')}.${name}`;

// ── simulated job ───────────────────────────────────────────────────────────
interface MockItem {
  record: Omit<TestRecord, 'status' | 'reason_code' | 'test_path'>;
  outcome: RecordStatus; // final outcome (shown once the item is "done")
  reason: string | null;
  testPath: string;
}
interface MockJob {
  id: string;
  projectId: string;
  version: number;
  levels: TestLevel[];
  files: TreeFile[]; // selected files (python + skipped ones)
  items: MockItem[];
  startedAt: number;
  cancelledAt?: number;
}

const jobs = new Map<string, MockJob>();
let counter = 100;

const PENDING_MS = 900;
const PLAN_MS = 1200;
const ITEM_MS = 450;
const ACCEPT_MS = 1200;

interface Snapshot {
  status: JobStatus;
  stage: string;
  done: number;
}

const snapshot = (job: MockJob, now = Date.now()): Snapshot => {
  const t = (job.cancelledAt ?? now) - job.startedAt;
  const total = job.items.length;
  let snap: Snapshot;
  if (t < PENDING_MS) {
    snap = { status: 'pending', stage: 'queued', done: 0 };
  } else if (t < PENDING_MS + PLAN_MS) {
    snap = { status: 'running', stage: t < PENDING_MS + PLAN_MS / 2 ? 'checking_analysis' : 'planning', done: 0 };
  } else {
    const gen = t - PENDING_MS - PLAN_MS;
    const done = Math.min(total, Math.floor(gen / ITEM_MS));
    if (done < total) {
      snap = { status: 'running', stage: done < total * 0.6 ? 'generating' : 'running_sandbox', done };
    } else if (gen < total * ITEM_MS + ACCEPT_MS) {
      snap = { status: 'running', stage: 'accepting', done };
    } else {
      const issues = job.items.some((i) => i.outcome !== 'ready');
      snap = { status: issues ? 'completed_with_issues' : 'completed', stage: 'done', done };
    }
  }
  if (job.cancelledAt) snap = { ...snap, status: 'cancelled' };
  return snap;
};

const itemStatus = (job: MockJob, idx: number, done: number): RecordStatus =>
  idx < done ? job.items[idx].outcome : 'pending';

const worst = (list: RecordStatus[]): RecordStatus => {
  if (list.includes('pending')) return 'pending';
  for (const s of ['generation_failed', 'test_failed', 'environment_error', 'skipped'] as RecordStatus[]) {
    if (list.includes(s)) return s;
  }
  return 'ready';
};

const buildFiles = (job: MockJob, done: number): JobFile[] =>
  job.files.map((f): JobFile => {
    if (!isPython(f)) return { path: f.filepath, status: 'skipped', reason: 'unsupported_language' };
    const levels: Partial<Record<TestLevel, RecordStatus>> = {};
    const all: RecordStatus[] = [];
    for (const level of job.levels) {
      const st: RecordStatus[] = [];
      job.items.forEach((it, idx) => {
        if (it.record.file === f.filepath && it.record.level === level) st.push(itemStatus(job, idx, done));
      });
      levels[level] = worst(st);
      all.push(levels[level] as RecordStatus);
    }
    let status: FileStatus;
    if (all.every((s) => s === 'pending')) status = 'pending';
    else if (all.every((s) => s === 'ready')) status = 'ready';
    else if (all.includes('pending') || all.includes('ready')) status = 'partial';
    else status = 'failed';
    return { path: f.filepath, status, levels, reason: null };
  });


const readFlag = (name: string): string | null => {
  try {
    return localStorage.getItem(name);
  } catch {
    return null;
  }
};

/** Builds a simulated job (shared by "start" and by the seeded history). */
const makeJob = (projectId: string, version: number, levels: TestLevel[], paths: string[], startedAt: number): MockJob => {
  const versionFiles = ALL_FILES.slice(0, FILES_BY_VERSION[version] ?? ALL_FILES.length);
  const selected = paths.length === 0 ? versionFiles : versionFiles.filter((f) => paths.includes(f.filepath));
  const python = selected.filter(isPython);
  if (python.length === 0) throw new ApiProblem(422, 'no_python_files', 'No Python files selected');

  counter++;
  const id = `job_${counter.toString(16)}a${(counter * 7).toString(16)}`;
  const items: MockItem[] = [];
  let n = 0;
  for (const f of python) {
    for (const name of UNIT_NAMES[f.filepath] ?? ['main']) {
      for (const level of levels) {
        n++;
        const outcome: RecordStatus = n % 9 === 4 ? 'generation_failed' : n % 13 === 6 ? 'test_failed' : 'ready';
        const base = f.filename.replace(/\.py$/, '');
        items.push({
          record: { id: `t_${counter}_${n}`, file: f.filepath, unit_id: toUnitId(f.filepath, name), level },
          outcome,
          reason: outcome === 'generation_failed' ? 'invalid_after_repair' : outcome === 'test_failed' ? 'assertion_failed' : null,
          testPath: `tests/generated/test_${base}_${name.replace(/\./g, '_').toLowerCase()}_${level}.py`,
        });
      }
    }
  }
  const job: MockJob = { id, projectId, version, levels, files: selected, items, startedAt };
  jobs.set(id, job);
  return job;
};

const DAY = 24 * 60 * 60 * 1000;
const seeded = new Set<string>();
/** Gives each project two finished earlier runs (unless tests:mock:fresh is set). */
const seedHistory = (projectId: string) => {
  if (seeded.has(projectId) || readFlag('tests:mock:fresh') === '1') return;
  seeded.add(projectId);
  makeJob(projectId, 1, ['unit', 'edge', 'integration'], [], Date.now() - 5 * DAY);
  makeJob(projectId, 2, ['unit'], [], Date.now() - 2 * DAY);
};

const progressOf = (job: MockJob, snap: Snapshot): JobProgress => {
  const total = snap.stage === 'queued' || snap.stage === 'checking_analysis' ? 0 : job.items.length;
  const by: Partial<Record<RecordStatus, number>> = {};
  job.items.forEach((_, idx) => {
    const s = itemStatus(job, idx, snap.done);
    by[s] = (by[s] ?? 0) + (total === 0 ? 0 : 1);
  });
  return { total, done: snap.done, by_status: by };
};

const toSummary = (job: MockJob): JobSummary => {
  const snap = snapshot(job);
  return {
    job_id: job.id,
    project_id: job.projectId,
    version_number: job.version,
    status: snap.status,
    created_at: new Date(job.startedAt).toISOString(),
    progress: progressOf(job, snap),
  };
};

const readFail = (): string | null => {
  try {
    return localStorage.getItem('tests:mock:fail');
  } catch {
    return null;
  }
};

const getJobOrThrow = (id: string): MockJob => {
  const job = jobs.get(id);
  if (!job) throw new ApiProblem(404, 'not_found', 'Job not found');
  return job;
};

// ── API ─────────────────────────────────────────────────────────────────────
export const mockTestsApi: TestsApi = {
  async getVersions(projectId): Promise<VersionsResponse> {
    await delay();
    return { project_id: projectId, project_name: PROJECT_NAME, versions: VERSIONS };
  },

  async getTree(projectId, version): Promise<TreeResponse> {
    await delay();
    const count = FILES_BY_VERSION[version] ?? ALL_FILES.length;
    // v1 has the four files that existed first; later versions add the rest
    const files = ALL_FILES.slice(0, count);
    return { project_id: projectId, project_name: PROJECT_NAME, version_number: version, flat_files: files };
  },

  async createJob(body: CreateJobRequest): Promise<CreateJobResponse> {
    await delay(400);
    const fail = readFail();
    if (fail === 'network') throw new ApiProblem(0, 'network', 'Network Error');
    if (fail === 'forbidden') throw new ApiProblem(403, 'forbidden', 'Forbidden');
    if (fail === 'analysis_missing') throw new ApiProblem(409, 'analysis_missing', 'Analysis missing');
    if (!body.levels || body.levels.length === 0) throw new ApiProblem(400, 'validation_error', 'levels is empty');

    const job = makeJob(body.project_id, body.version_number ?? VERSIONS[0].version_number, body.levels, body.paths, Date.now());
    return { job_id: job.id, status: 'pending', project_id: body.project_id, version_number: job.version };
  },

  async listJobs(projectId): Promise<JobHistory> {
    await delay();
    seedHistory(projectId);
    const items = [...jobs.values()]
      .filter((j) => j.projectId === projectId)
      .sort((a, b) => b.startedAt - a.startedAt)
      .map(toSummary);
    return { items, source: readFlag('tests:mock:history') === 'local' ? 'local' : 'server' };
  },

  async getJob(jobId): Promise<JobDetail> {
    await delay(120);
    const job = getJobOrThrow(jobId);
    const snap = snapshot(job);
    const progress = progressOf(job, snap);
    return {
      job_id: job.id,
      project_id: job.projectId,
      version_number: job.version,
      status: snap.status,
      stage: snap.stage,
      progress,
      files: progress.total === 0 ? [] : buildFiles(job, snap.done),
      error: null,
    };
  },

  async getPlan(jobId): Promise<PlanResponse> {
    await delay();
    const job = getJobOrThrow(jobId);
    const seen = new Set<string>();
    const units: PlanResponse['units'] = [];
    for (const it of job.items) {
      if (seen.has(it.record.unit_id)) continue;
      seen.add(it.record.unit_id);
      units.push({ id: it.record.unit_id, file: it.record.file, kind: it.record.unit_id.includes('.__init__') ? 'constructor' : /[A-Z]\w+\.\w+$/.test(it.record.unit_id) ? 'method' : 'function' });
    }
    const skipped = job.files.filter((f) => !isPython(f)).map((f) => ({ path: f.filepath, reason: 'unsupported_language' }));
    return { units, skipped, work_items_count: job.items.length };
  },

  async getRecords(jobId, filter: RecordsFilter = {}): Promise<RecordsResponse> {
    await delay();
    const job = getJobOrThrow(jobId);
    const snap = snapshot(job);
    let items: TestRecord[] = job.items.map((it, idx) => {
      const status = itemStatus(job, idx, snap.done);
      return {
        ...it.record,
        status,
        reason_code: status === 'pending' ? null : it.reason,
        test_path: status === 'ready' ? it.testPath : null,
      };
    });
    if (filter.status) items = items.filter((i) => i.status === filter.status);
    if (filter.level) items = items.filter((i) => i.level === filter.level);
    if (filter.path) items = items.filter((i) => i.file === filter.path);
    return { items, total: items.length };
  },

  async getCoverage(jobId): Promise<CoverageResponse> {
    await delay();
    const job = getJobOrThrow(jobId);
    const snap = snapshot(job);
    if (!isTerminalJob(snap.status) || snap.status === 'cancelled') {
      throw new ApiProblem(409, 'coverage_not_ready', 'Coverage is not ready yet');
    }
    const files = job.files
      .filter(isPython)
      .filter((f) => job.items.some((i) => i.record.file === f.filepath && i.outcome === 'ready'))
      .map((f) => {
        const h = hash(f.filepath);
        const line = 52 + (h % 44);
        const branch = Math.max(20, line - 6 - (h % 17));
        const missing: number[] = [];
        let ln = 8 + (h % 10);
        for (let i = 0; i < Math.round((100 - line) / 4); i++) {
          missing.push(ln);
          ln += 1 + ((h >> i) % 6);
        }
        return { path: f.filepath, line_percent: line, branch_percent: branch, missing_lines: missing };
      });
    const avg = (k: 'line_percent' | 'branch_percent') =>
      files.length ? Math.round((files.reduce((a, f) => a + f[k], 0) / files.length) * 10) / 10 : 0;
    return { line_percent: avg('line_percent'), branch_percent: avg('branch_percent'), files };
  },

  async cancelJob(jobId) {
    await delay(300);
    const job = getJobOrThrow(jobId);
    if (isTerminalJob(snapshot(job).status)) throw new ApiProblem(409, 'conflict', 'Job already finished');
    job.cancelledAt = Date.now();
    return { job_id: job.id, status: 'cancelled' as JobStatus };
  },

  async downloadZip(jobId) {
    await delay(500);
    const job = getJobOrThrow(jobId);
    const snap = snapshot(job);
    const ready = job.items.filter((_, idx) => itemStatus(job, idx, snap.done) === 'ready');
    if (ready.length === 0) throw new ApiProblem(409, 'no_ready_tests', 'No ready tests');
    const text =
      `MOCK DOWNLOAD (the real back-end returns a ZIP of ready tests only)\n` +
      `job: ${job.id}\nversion: ${job.version}\n\n` +
      ready.map((r) => r.testPath).join('\n');
    return { blob: new Blob([text], { type: 'text/plain' }), filename: `tests_${job.id}_MOCK.txt` };
  },
};