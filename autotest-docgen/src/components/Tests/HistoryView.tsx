/**
 * components/Tests/HistoryView.tsx   ("Tested")
 * Earlier test runs of ONE project. Click a run to open its results.
 *
 * Data: testsApi.listJobs(projectId)
 *   - server list   when the back-end provides  GET /api/analysis/tests/jobs/?project_id=
 *   - browser list  otherwise (only runs started from this browser) -> a note says so.
 * "Open by job ID" also works for jobs that are not in the list (e.g. a reviewer opening a shared id).
 */
import React, { useState } from 'react';
import { ChevronRight, History, Loader2, Play } from 'lucide-react';
import { testsApi } from '../../services/testsApi.service';
import { useJobResource } from '../../hooks/useTestJob';
import { useTestsT } from '../../locales/testsTranslations';
import { StatusBadge } from './badges';
import ErrorBanner from './ErrorBanner';
import { formatWhen } from './format';
import type { TestsProject } from './TestsModalHost';

interface Props {
  project: TestsProject;
  canGenerate: boolean;
  onOpen: (jobId: string) => void;
  onNewRun: () => void;
}

const HistoryView: React.FC<Props> = ({ project, canGenerate, onOpen, onNewRun }) => {
  const { t, language } = useTestsT();
  const [reload, setReload] = useState(0);
  const [manualId, setManualId] = useState('');
  const { data, loading, error } = useJobResource(() => testsApi.listJobs(project.id), `${project.id}|${reload}`);

  const items = data?.items ?? [];

  return (
    <div className="tp-history">
      <div className="tp-history-head">
        <p className="tp-muted tp-intro">{t('history.subtitle')}</p>
        {canGenerate && items.length > 0 && (
          <button type="button" className="tp-btn tp-btn--primary tp-btn--sm" onClick={onNewRun}>
            <Play size={14} />{t('history.new')}
          </button>
        )}
      </div>

      {loading && !data && <div className="tp-muted tp-row tp-pad"><Loader2 size={16} className="tp-spin" /> {t('common.loading')}</div>}

      <ErrorBanner problem={error} onRetry={() => setReload((n) => n + 1)} />

      {data && items.length === 0 && (
        <div className="tp-emptyblock">
          <History size={34} className="tp-muted" />
          <h3>{t('history.empty.title')}</h3>
          <p className="tp-muted">{t('history.empty.text')}</p>
          {canGenerate && (
            <button type="button" className="tp-btn tp-btn--primary" onClick={onNewRun}>
              <Play size={16} />{t('history.empty.cta')}
            </button>
          )}
        </div>
      )}

      {items.length > 0 && (
        <ul className="tp-runs">
          {items.map((r) => {
            const total = r.progress?.total ?? 0;
            const ready = r.progress?.by_status?.ready ?? 0;
            return (
              <li key={r.job_id}>
                <button type="button" className="tp-run" onClick={() => onOpen(r.job_id)}>
                  <div className="tp-run-main">
                    <div className="tp-run-title">
                      <strong>{t('history.version', { v: r.version_number })}</strong>
                      <StatusBadge status={r.status} />
                    </div>
                    <div className="tp-muted tp-small">{formatWhen(r.created_at, language)} · <code>{r.job_id}</code></div>
                  </div>
                  <div className="tp-run-side tp-small tp-muted">
                    {total > 0 && <span>{t('history.tests', { done: r.progress?.done ?? 0, total })}</span>}
                    {ready > 0 && <span className="tp-run-ready">{t('history.ready', { n: ready })}</span>}
                  </div>
                  <ChevronRight size={18} className="tp-chev tp-muted" />
                </button>
              </li>
            );
          })}
        </ul>
      )}

      {data?.source === 'local' && items.length > 0 && <div className="tp-muted tp-small tp-localnote">{t('history.localNote')}</div>}

      <form
        className="tp-openbyid tp-openbyid--footer"
        onSubmit={(e) => { e.preventDefault(); if (manualId.trim()) onOpen(manualId.trim()); }}
      >
        <input className="tp-input" value={manualId} onChange={(e) => setManualId(e.target.value)} placeholder={t('job.openPlaceholder')} aria-label={t('history.openById')} />
        <button type="submit" className="tp-btn tp-btn--ghost" disabled={!manualId.trim()}>{t('job.open')}</button>
      </form>
    </div>
  );
};

export default HistoryView;