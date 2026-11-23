/**
 * components/Tests/RecordsTable.tsx  (export: RecordsTab)
 * GET /jobs/{id}/records/  with the server-side filters ?status ?level ?path.
 * One row per (unit x level). Shows the generated test file path for ready tests.
 *
 * Note: the approved API gives `test_path` only. There is no endpoint for the
 * test source code, attempts or model, so there is no "test detail" drawer yet.
 */
import React, { useEffect, useState } from 'react';
import { Loader2 } from 'lucide-react';
import { testsApi } from '../../services/testsApi.service';
import { useJobResource } from '../../hooks/useTestJob';
import { useTestsT } from '../../locales/testsTranslations';
import { ALL_LEVELS, type JobFile, type RecordStatus, type TestLevel } from '../../types/tests';
import { LevelPill } from './badges';
import ErrorBanner from './ErrorBanner';

const STATUSES: RecordStatus[] = ['ready', 'test_failed', 'generation_failed', 'environment_error', 'skipped', 'pending'];
const PAGE_SIZE = 25;

interface Props {
  jobId: string;
  files: JobFile[];
  /** changes whenever the job progressed, so the table reloads while the job runs */
  refreshKey: string;
}

const RecordsTab: React.FC<Props> = ({ jobId, files, refreshKey }) => {
  const { t, label } = useTestsT();
  const [status, setStatus] = useState<RecordStatus | ''>('');
  const [level, setLevel] = useState<TestLevel | ''>('');
  const [path, setPath] = useState('');
  const [page, setPage] = useState(0);

  const { data, loading, error } = useJobResource(
    () => testsApi.getRecords(jobId, { status, level, path }),
    `${jobId}|${status}|${level}|${path}|${refreshKey}`,
  );

  // filters changed -> go back to the first page
  useEffect(() => setPage(0), [status, level, path]);

  const items = data?.items ?? [];
  const pages = Math.max(1, Math.ceil(items.length / PAGE_SIZE));
  const slice = items.slice(page * PAGE_SIZE, page * PAGE_SIZE + PAGE_SIZE);

  return (
    <div>
      <div className="tp-filters">
        <label>
          <span>{t('records.status')}</span>
          <select className="tp-input" value={status} onChange={(e) => setStatus(e.target.value as RecordStatus | '')}>
            <option value="">{t('records.all')}</option>
            {STATUSES.map((s) => <option key={s} value={s}>{label('status', s)}</option>)}
          </select>
        </label>
        <label>
          <span>{t('records.level')}</span>
          <select className="tp-input" value={level} onChange={(e) => setLevel(e.target.value as TestLevel | '')}>
            <option value="">{t('records.all')}</option>
            {ALL_LEVELS.map((l) => <option key={l} value={l}>{t(`level.${l}` as 'level.unit')}</option>)}
          </select>
        </label>
        <label className="tp-grow">
          <span>{t('records.file')}</span>
          <select className="tp-input" value={path} onChange={(e) => setPath(e.target.value)}>
            <option value="">{t('records.all')}</option>
            {files.map((f) => <option key={f.path} value={f.path}>{f.path}</option>)}
          </select>
        </label>
        {loading && <Loader2 size={16} className="tp-spin tp-filter-spin" />}
      </div>

      <ErrorBanner problem={error} />

      {!error && items.length === 0 && !loading && <div className="tp-empty">{t('records.empty')}</div>}

      {items.length > 0 && (
        <>
          <div className="tp-tablewrap">
            <table className="tp-table">
              <thead>
                <tr>
                  <th>{t('records.unit')}</th>
                  <th>{t('records.level')}</th>
                  <th>{t('records.status')}</th>
                  <th>{t('records.testFile')}</th>
                </tr>
              </thead>
              <tbody>
                {slice.map((r) => (
                  <tr key={r.id}>
                    <td>
                      <div className="tp-mono" title={r.unit_id}>{r.unit_id}</div>
                      <div className="tp-muted tp-small tp-filepath" title={r.file}>{r.file}</div>
                    </td>
                    <td>{t(`level.${r.level}` as 'level.unit')}</td>
                    <td>
                      <LevelPill status={r.status} />
                      {r.reason_code && <div className="tp-muted tp-small tp-reason">{label('reason', r.reason_code)}</div>}
                    </td>
                    <td>{r.test_path ? <span className="tp-mono tp-filepath" title={r.test_path}>{r.test_path}</span> : <span className="tp-dash">—</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="tp-pager">
            <span className="tp-muted tp-small">{t('records.showing', { n: slice.length, total: items.length })}</span>
            <div>
              <button type="button" className="tp-btn tp-btn--ghost tp-btn--sm" disabled={page === 0} onClick={() => setPage((p) => p - 1)}>
                {t('records.prev')}
              </button>
              <span className="tp-small tp-pagenum">{page + 1} / {pages}</span>
              <button type="button" className="tp-btn tp-btn--ghost tp-btn--sm" disabled={page + 1 >= pages} onClick={() => setPage((p) => p + 1)}>
                {t('records.next')}
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
};

export default RecordsTab;