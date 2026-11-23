/**
 * components/Tests/PlanPanel.tsx  (export: PlanTab)
 * GET /jobs/{id}/plan/ : units that will be tested, files that were skipped and why,
 * and the total number of work items (unit x level).
 */
import React from 'react';
import { Loader2 } from 'lucide-react';
import { testsApi } from '../../services/testsApi.service';
import { useJobResource } from '../../hooks/useTestJob';
import { useTestsT } from '../../locales/testsTranslations';

const PlanTab: React.FC<{ jobId: string }> = ({ jobId }) => {
  const { t, label } = useTestsT();
  const { data, loading, error } = useJobResource(() => testsApi.getPlan(jobId), jobId);

  if (loading && !data) return <div className="tp-muted tp-row"><Loader2 size={16} className="tp-spin" /> {t('common.loading')}</div>;
  if (error || !data) return <div className="tp-empty">{t('plan.none')}</div>;

  return (
    <div>
      <div className="tp-counters">
        <div className="tp-counter"><div className="tp-counter-num">{data.work_items_count}</div><div className="tp-counter-label">{t('plan.workItems')}</div></div>
        <div className="tp-counter"><div className="tp-counter-num">{data.units.length}</div><div className="tp-counter-label">{t('plan.units')}</div></div>
        <div className="tp-counter tp-counter--skipped"><div className="tp-counter-num">{data.skipped.length}</div><div className="tp-counter-label">{t('plan.skipped')}</div></div>
      </div>

      <div className="tp-tablewrap">
        <table className="tp-table">
          <thead>
            <tr><th>{t('plan.unit')}</th><th>{t('plan.file')}</th><th>{t('plan.kind')}</th></tr>
          </thead>
          <tbody>
            {data.units.map((u) => (
              <tr key={u.id}>
                <td><span className="tp-mono" title={u.id}>{u.id}</span></td>
                <td><span className="tp-filepath" title={u.file}>{u.file}</span></td>
                <td className="tp-muted">{u.kind}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h4 className="tp-subtitle">{t('plan.skipped')}</h4>
      {data.skipped.length === 0 ? (
        <div className="tp-muted tp-small">{t('plan.noSkipped')}</div>
      ) : (
        <div className="tp-tablewrap">
          <table className="tp-table">
            <tbody>
              {data.skipped.map((s) => (
                <tr key={s.path}>
                  <td><span className="tp-filepath" title={s.path}>{s.path}</span></td>
                  <td className="tp-muted">{label('reason', s.reason)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};

export default PlanTab;