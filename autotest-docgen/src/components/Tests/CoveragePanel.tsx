/**
 * components/Tests/CoveragePanel.tsx  (export: CoverageTab)
 * GET /jobs/{id}/coverage/ : overall line/branch % + per-FILE rows with missing lines.
 * Coverage is per file (not per unit) in the approved API, and is measured on the
 * final all-pass run of the ready tests.
 */
import React from 'react';
import { Loader2 } from 'lucide-react';
import { testsApi } from '../../services/testsApi.service';
import { useJobResource } from '../../hooks/useTestJob';
import { useTestsT } from '../../locales/testsTranslations';

interface Props {
  jobId: string;
  /** coverage exists only after the job finished */
  enabled: boolean;
  refreshKey: string;
}

const colorFor = (p: number) => (p >= 80 ? 'ok' : p >= 60 ? 'warn' : 'bad');

/** 42,43,44,55 -> "42–44, 55" */
const toRanges = (lines: number[]): string[] => {
  const sorted = [...lines].sort((a, b) => a - b);
  const out: string[] = [];
  let start = sorted[0];
  let prev = sorted[0];
  for (let i = 1; i <= sorted.length; i++) {
    const cur = sorted[i];
    if (cur === prev + 1) { prev = cur; continue; }
    if (start !== undefined) out.push(start === prev ? `${start}` : `${start}–${prev}`);
    start = cur;
    prev = cur;
  }
  return out;
};

const Ring: React.FC<{ value: number; title: string }> = ({ value, title }) => {
  const r = 42;
  const c = 2 * Math.PI * r;
  const v = Math.max(0, Math.min(100, value));
  return (
    <div className="tp-ring">
      <svg viewBox="0 0 100 100" width="104" height="104" aria-hidden="true">
        <circle cx="50" cy="50" r={r} className="tp-ring-track" />
        <circle
          cx="50" cy="50" r={r}
          className={`tp-ring-val tp-ring-val--${colorFor(v)}`}
          strokeDasharray={`${(v / 100) * c} ${c}`}
          transform="rotate(-90 50 50)"
        />
      </svg>
      <div className="tp-ring-text">
        <strong>{v.toFixed(1)}%</strong>
        <span>{title}</span>
      </div>
    </div>
  );
};

const Bar: React.FC<{ value: number }> = ({ value }) => (
  <div className="tp-minibar">
    <div className="tp-minibar-track"><div className={`tp-minibar-fill tp-minibar-fill--${colorFor(value)}`} style={{ width: `${value}%` }} /></div>
    <span className="tp-small">{value.toFixed(1)}%</span>
  </div>
);

const CoverageTab: React.FC<Props> = ({ jobId, enabled, refreshKey }) => {
  const { t } = useTestsT();
  const { data, loading, error } = useJobResource(
    enabled ? () => testsApi.getCoverage(jobId) : null,
    `${jobId}|${enabled}|${refreshKey}`,
  );

  if (!enabled) return <div className="tp-empty">{t('coverage.none')}</div>;
  if (loading && !data) return <div className="tp-muted tp-row"><Loader2 size={16} className="tp-spin" /> {t('common.loading')}</div>;
  // 404 / 409 here only means "not produced (yet)": show the neutral message instead of an error
  if (error || !data) return <div className="tp-empty">{t('coverage.none')}</div>;
  if (data.files.length === 0) return <div className="tp-empty">{t('coverage.noFiles')}</div>;

  return (
    <div>
      <div className="tp-rings">
        <Ring value={data.line_percent} title={t('coverage.line')} />
        <Ring value={data.branch_percent} title={t('coverage.branch')} />
        <div className="tp-muted tp-small tp-ringnote">{t('coverage.note')}</div>
      </div>

      <div className="tp-tablewrap">
        <table className="tp-table">
          <thead>
            <tr>
              <th>{t('coverage.file')}</th>
              <th>{t('coverage.lines')}</th>
              <th>{t('coverage.branches')}</th>
              <th>{t('coverage.missing')}</th>
            </tr>
          </thead>
          <tbody>
            {data.files.map((f) => {
              const ranges = toRanges(f.missing_lines);
              const shown = ranges.slice(0, 6);
              return (
                <tr key={f.path}>
                  <td><span className="tp-filepath" title={f.path}>{f.path}</span></td>
                  <td><Bar value={f.line_percent} /></td>
                  <td><Bar value={f.branch_percent} /></td>
                  <td>
                    <div className="tp-chips" title={ranges.join(', ')}>
                      {shown.map((r) => <span key={r} className="tp-chip">{r}</span>)}
                      {ranges.length > shown.length && <span className="tp-chip tp-chip--more">{t('coverage.more', { n: ranges.length - shown.length })}</span>}
                      {ranges.length === 0 && <span className="tp-dash">—</span>}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
};

export default CoverageTab;