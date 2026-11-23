/**
 * components/Tests/JobProgressCard.tsx
 * Status, stage, progress bar, status counters, error box and the job actions
 * (cancel / download / copy link / refresh). Purely presentational: the page owns the handlers.
 */
import React, { useState } from 'react';
import { Ban, Check, Copy, Download, Loader2, RefreshCw } from 'lucide-react';
import { useTestsT } from '../../locales/testsTranslations';
import { isTerminalJob, type JobDetail, type JobError, type RecordStatus } from '../../types/tests';
import { StatusBadge } from './badges';

interface Props {
  job: JobDetail;
  canGenerate: boolean;
  cancelling: boolean;
  downloading: boolean;
  onCancel: () => void;
  onDownload: () => void;
  onRefresh: () => void;
}

const COUNTER_ORDER: RecordStatus[] = [
  'ready', 'test_failed', 'generation_failed', 'environment_error', 'skipped', 'pending',
];

/** `error` may be a string or { code, message } (shape not final): handle both. */
const describeError = (e: JobError): { code?: string; message?: string } | null => {
  if (!e) return null;
  if (typeof e === 'string') return { message: e };
  return { code: e.code, message: e.message };
};

const JobProgressCard: React.FC<Props> = ({ job, canGenerate, cancelling, downloading, onCancel, onDownload, onRefresh }) => {
  const { t, label } = useTestsT();
  const [copied, setCopied] = useState(false);

  const terminal = isTerminalJob(job.status);
  const { total, done, by_status: by } = job.progress;
  const percent = total > 0 ? Math.min(100, Math.round((done / total) * 100)) : 0;
  const readyCount = by.ready ?? 0;
  const err = describeError(job.error);
  const summaryKey = `job.summary.${job.status}` as Parameters<typeof t>[0];
  const summary = t(summaryKey);

  const copyLink = async () => {
    try {
      await navigator.clipboard.writeText(`${window.location.origin}/dashboard?testproject=${encodeURIComponent(job.project_id)}&testjob=${encodeURIComponent(job.job_id)}`);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard may be blocked: ignore */
    }
  };

  return (
    <section className="tp-card">
      <div className="tp-jobhead">
        <div>
          <div className="tp-muted tp-small">{t('job.label')}</div>
          <div className="tp-jobid">
            <code>{job.job_id}</code>
            <button type="button" className="tp-icon-btn" onClick={copyLink} title={t('job.copyLink')}>
              {copied ? <Check size={15} /> : <Copy size={15} />}
            </button>
            {copied && <span className="tp-small tp-muted">{t('job.copied')}</span>}
          </div>
        </div>
        <div className="tp-jobmeta">
          <span className="tp-tag">{t('job.version', { v: job.version_number })}</span>
          <StatusBadge status={job.status} />
        </div>
      </div>

      {/* stage + progress */}
      <div className="tp-stagerow">
        <span className="tp-muted">{t('job.stage')}:</span>
        <strong>{job.stage ? label('stage', job.stage) : '—'}</strong>
        {!terminal && <Loader2 size={14} className="tp-spin" />}
      </div>

      <div className={`tp-bar ${!terminal && total === 0 ? 'is-indeterminate' : ''}`} role="progressbar" aria-valuenow={percent} aria-valuemin={0} aria-valuemax={100}>
        <div className="tp-bar-fill" style={{ width: total > 0 ? `${percent}%` : undefined }} />
      </div>
      <div className="tp-muted tp-small">
        {total > 0 ? t('job.progress', { done, total }) : t('job.preparing')}
        {total > 0 && <strong> · {percent}%</strong>}
      </div>

      {/* counters */}
      {total > 0 && (
        <div className="tp-counters">
          {COUNTER_ORDER.filter((s) => (by[s] ?? 0) > 0 || s === 'ready').map((s) => (
            <div key={s} className={`tp-counter tp-counter--${s}`}>
              <div className="tp-counter-num">{by[s] ?? 0}</div>
              <div className="tp-counter-label">{label('status', s)}</div>
            </div>
          ))}
        </div>
      )}

      {/* result summary / error */}
      {terminal && summary !== summaryKey && (
        <div className={`tp-note tp-note--${job.status}`}>{summary}</div>
      )}
      {err && (
        <div className="tp-alert tp-alert--error">
          <div className="tp-alert-body">
            <div>{err.message ?? (err.code ? label('err', err.code) : t('err.unknown'))}</div>
            {err.code && <div className="tp-alert-meta"><code>{err.code}</code></div>}
          </div>
        </div>
      )}

      {/* actions */}
      <div className="tp-actions">
        <button
          type="button"
          className="tp-btn tp-btn--primary"
          disabled={!terminal || readyCount === 0 || downloading}
          onClick={onDownload}
          title={!terminal || readyCount === 0 ? t('job.downloadHint') : undefined}
        >
          {downloading ? <Loader2 size={16} className="tp-spin" /> : <Download size={16} />}
          {downloading ? t('job.downloading') : t('job.download')}
        </button>

        {canGenerate && !terminal && (
          <button type="button" className="tp-btn tp-btn--danger" disabled={cancelling} onClick={onCancel}>
            {cancelling ? <Loader2 size={16} className="tp-spin" /> : <Ban size={16} />}
            {cancelling ? t('job.cancelling') : t('job.cancel')}
          </button>
        )}

        <button type="button" className="tp-btn tp-btn--ghost" onClick={onRefresh}>
          <RefreshCw size={16} />
          {t('job.refresh')}
        </button>
      </div>
    </section>
  );
};

export default JobProgressCard;