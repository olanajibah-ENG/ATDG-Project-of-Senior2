/**
 * hooks/useTestJob.ts
 * ---------------------------------------------------------------------------
 * useTestJob      : polls GET /jobs/{id}/ every 2s until the job is finished.
 * useJobResource  : small loader for plan / records / coverage (keeps old data
 *                   while reloading, so tables do not flicker during polling).
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { testsApi } from '../services/testsApi.service';
import { toProblem } from '../services/testsApi.service';
import { ApiProblem, isTerminalJob, type JobDetail } from '../types/tests';

const POLL_MS = 2000;
const MAX_TRANSIENT_FAILURES = 4;

export interface UseTestJob {
  job: JobDetail | null;
  loading: boolean;
  /** Fatal error (404 / 403 / 401 / repeated network failure). Polling has stopped. */
  error: ApiProblem | null;
  isTerminal: boolean;
  /** Restart polling immediately (also used after cancel). */
  refresh: () => void;
}

export function useTestJob(jobId: string | null): UseTestJob {
  const [job, setJob] = useState<JobDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<ApiProblem | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const timer = useRef<number | undefined>(undefined);

  useEffect(() => {
    window.clearTimeout(timer.current);
    if (!jobId) {
      setJob(null);
      setError(null);
      setLoading(false);
      return;
    }

    let stopped = false;
    let failures = 0;
    setLoading(true);
    setError(null);

    const tick = async () => {
      try {
        const next = await testsApi.getJob(jobId);
        if (stopped) return;
        failures = 0;
        setJob(next);
        setError(null);
        setLoading(false);
        if (!isTerminalJob(next.status)) timer.current = window.setTimeout(tick, POLL_MS);
      } catch (e) {
        if (stopped) return;
        const problem = toProblem(e);
        const fatal = [401, 403, 404].includes(problem.status);
        failures += 1;
        if (fatal || failures >= MAX_TRANSIENT_FAILURES) {
          setError(problem);
          setLoading(false);
          return;
        }
        // transient problem (network blip / 5xx): back off and try again
        timer.current = window.setTimeout(tick, POLL_MS * Math.min(failures + 1, 4));
      }
    };

    void tick();
    return () => {
      stopped = true;
      window.clearTimeout(timer.current);
    };
  }, [jobId, reloadKey]);

  const refresh = useCallback(() => setReloadKey((k) => k + 1), []);

  return { job, loading, error, isTerminal: job ? isTerminalJob(job.status) : false, refresh };
}

export interface UseJobResource<T> {
  data: T | null;
  loading: boolean;
  error: ApiProblem | null;
}

/**
 * Loads a resource whenever `key` changes. Pass `load = null` to disable.
 * Old data is kept while a new request is in flight.
 */
export function useJobResource<T>(load: (() => Promise<T>) | null, key: string): UseJobResource<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<ApiProblem | null>(null);

  useEffect(() => {
    if (!load) {
      setData(null);
      setError(null);
      setLoading(false);
      return;
    }
    let stopped = false;
    setLoading(true);
    load()
      .then((d) => {
        if (stopped) return;
        setData(d);
        setError(null);
      })
      .catch((e) => {
        if (stopped) return;
        setError(toProblem(e));
      })
      .finally(() => {
        if (!stopped) setLoading(false);
      });
    return () => {
      stopped = true;
    };
    // `key` is the single source of truth for "reload now"
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  return { data, loading, error };
}