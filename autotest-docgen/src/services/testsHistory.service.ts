/**
 * services/testsHistory.service.ts
 * ---------------------------------------------------------------------------
 * Remembers, per project and per browser, the jobs that were started here.
 * It is only the FALLBACK for the "Tested" list: the approved API has no
 * "list jobs" endpoint. Once the back-end provides
 *     GET /api/analysis/tests/jobs/?project_id=<uuid>
 * the server list is used and this file is no longer needed (nothing else changes).
 *
 * Limits of the fallback: the list exists only in this browser, and is lost if
 * the browser data is cleared.
 */
export interface LocalRun {
  job_id: string;
  version_number: number;
  created_at: string;
}

const MAX_RUNS = 30;
const key = (projectId: string) => `tests:history:${projectId}`;

export const readLocalRuns = (projectId: string): LocalRun[] => {
  try {
    const raw = localStorage.getItem(key(projectId));
    const parsed: unknown = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed)
      ? (parsed as LocalRun[]).filter((r) => r && typeof r.job_id === 'string')
      : [];
  } catch {
    return [];
  }
};

const write = (projectId: string, runs: LocalRun[]) => {
  try {
    localStorage.setItem(key(projectId), JSON.stringify(runs.slice(0, MAX_RUNS)));
  } catch {
    /* storage unavailable: history simply is not kept */
  }
};

export const rememberRun = (projectId: string, run: LocalRun): void => {
  const rest = readLocalRuns(projectId).filter((r) => r.job_id !== run.job_id);
  write(projectId, [run, ...rest]);
};

export const forgetRun = (projectId: string, jobId: string): void => {
  write(projectId, readLocalRuns(projectId).filter((r) => r.job_id !== jobId));
};