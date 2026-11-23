/**
 * components/Tests/NewRunView.tsx
 * "New test run" popup body: the form (version, files, levels) plus a notice when the
 * project was tested before. Pressing Start on a project with earlier runs first asks
 * "Start a new run?" (that confirmation lives in JobConfigPanel).
 */
import React from 'react';
import { History, Info } from 'lucide-react';
import { testsApi } from '../../services/testsApi.service';
import { useJobResource } from '../../hooks/useTestJob';
import { useTestsT } from '../../locales/testsTranslations';
import { isTerminalJob, type CreateJobResponse } from '../../types/tests';
import JobConfigPanel from './JobConfigPanel';
import { formatWhen } from './format';
import type { TestsProject } from './TestsModalHost';

interface Props {
  project: TestsProject;
  onStarted: (res: CreateJobResponse) => void;
  onViewHistory: () => void;
  onOpenJob: (jobId: string) => void;
}

const NewRunView: React.FC<Props> = ({ project, onStarted, onViewHistory, onOpenJob }) => {
  const { t, label, language } = useTestsT();
  const { data, error } = useJobResource(() => testsApi.listJobs(project.id), project.id);

  // null = still loading; a failed lookup must not block starting a run
  const prior = data ? data.items : error ? [] : null;
  const last = prior && prior.length > 0 ? prior[0] : null;
  const running = prior?.find((r) => r.status !== 'unknown' && !isTerminalJob(r.status)) ?? null;

  return (
    <div className="tp-newrun">
      {running && (
        <div className="tp-banner tp-banner--demo">
          <Info size={16} />
          <div className="tp-banner-body">
            <strong>{t('newRun.running.title')}</strong>
            <div className="tp-small">{t('history.version', { v: running.version_number })} · {label('status', running.status)}</div>
          </div>
          <button type="button" className="tp-btn tp-btn--ghost tp-btn--sm" onClick={() => onOpenJob(running.job_id)}>{t('newRun.running.open')}</button>
        </div>
      )}

      {!running && last && (
        <div className="tp-banner">
          <History size={16} />
          <div className="tp-banner-body">
            <strong>{t('newRun.prior.title')}</strong>
            <div className="tp-small">
              {t('newRun.prior.last', { when: formatWhen(last.created_at, language), v: last.version_number, status: label('status', last.status) })}
            </div>
          </div>
          <button type="button" className="tp-btn tp-btn--ghost tp-btn--sm" onClick={onViewHistory}>{t('newRun.prior.view')}</button>
        </div>
      )}

      <JobConfigPanel projectId={project.id} priorRuns={prior} onViewHistory={onViewHistory} onStarted={onStarted} />
    </div>
  );
};

export default NewRunView;