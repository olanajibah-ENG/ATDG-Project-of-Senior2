/**
 * components/Tests/JobView.tsx
 * Results popup body for ONE job: progress card + tabs (Files | Tests | Coverage | Plan),
 * with cancel and download. Polls the job every ~2s until it is finished.
 */
import React, { useEffect, useState } from 'react';
import { Loader2 } from 'lucide-react';
import { saveBlob, testsApi, toProblem } from '../../services/testsApi.service';
import { forgetRun } from '../../services/testsHistory.service';
import { useTestJob } from '../../hooks/useTestJob';
import { useTestsT } from '../../locales/testsTranslations';
import { isTerminalJob, type ApiProblem } from '../../types/tests';
import JobProgressCard from './JobProgressCard';
import FilesProgressTable from './FilesProgressTable';
import RecordsTab from './RecordsTable';
import CoverageTab from './CoveragePanel';
import PlanTab from './PlanPanel';
import ErrorBanner from './ErrorBanner';

type TabId = 'files' | 'records' | 'coverage' | 'plan';
const TABS: TabId[] = ['files', 'records', 'coverage', 'plan'];

interface Props {
  projectId: string;
  jobId: string;
  canGenerate: boolean;
}

const JobView: React.FC<Props> = ({ projectId, jobId, canGenerate }) => {
  const { t } = useTestsT();
  const { job, loading, error: jobError, isTerminal, refresh } = useTestJob(jobId);
  const [tab, setTab] = useState<TabId>('files');
  const [cancelling, setCancelling] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [actionError, setActionError] = useState<ApiProblem | null>(null);

  // a job that no longer exists must disappear from the remembered list
  useEffect(() => {
    if (jobError?.status === 404) forgetRun(projectId, jobId);
  }, [jobError, projectId, jobId]);

  const handleCancel = async () => {
    setCancelling(true);
    setActionError(null);
    try {
      await testsApi.cancelJob(jobId);
      refresh();
    } catch (e) {
      setActionError(toProblem(e));
    } finally {
      setCancelling(false);
    }
  };

  const handleDownload = async () => {
    setDownloading(true);
    setActionError(null);
    try {
      const { blob, filename } = await testsApi.downloadZip(jobId);
      saveBlob(blob, filename);
    } catch (e) {
      setActionError(toProblem(e));
    } finally {
      setDownloading(false);
    }
  };

  if (!job && loading) {
    return <div className="tp-muted tp-row tp-pad"><Loader2 size={18} className="tp-spin" /> {t('job.loading')}</div>;
  }

  if (!job) {
    return (
      <div className="tp-jobview">
        <ErrorBanner problem={jobError} onRetry={jobError && jobError.status !== 404 ? refresh : undefined} />
        {jobError?.status === 404 && <div className="tp-muted">{t('job.notFound')}</div>}
      </div>
    );
  }

  const refreshKey = `${job.status}:${job.progress.done}:${job.progress.total}`;

  return (
    <div className="tp-jobview">
      <JobProgressCard
        job={job}
        canGenerate={canGenerate}
        cancelling={cancelling}
        downloading={downloading}
        onCancel={handleCancel}
        onDownload={handleDownload}
        onRefresh={refresh}
      />
      {jobError && <ErrorBanner problem={jobError} onRetry={refresh} />}
      <ErrorBanner problem={actionError} onDismiss={() => setActionError(null)} />

      <section className="tp-card">
        <div className="tp-tabs" role="tablist">
          {TABS.map((id) => (
            <button key={id} type="button" role="tab" aria-selected={tab === id} className={tab === id ? 'is-active' : ''} onClick={() => setTab(id)}>
              {t(`tabs.${id}` as 'tabs.files')}
            </button>
          ))}
        </div>

        {tab === 'files' && <FilesProgressTable files={job.files} />}
        {tab === 'records' && <RecordsTab jobId={job.job_id} files={job.files} refreshKey={refreshKey} />}
        {tab === 'coverage' && (
          <CoverageTab jobId={job.job_id} enabled={isTerminal && job.status !== 'cancelled'} refreshKey={isTerminalJob(job.status) ? job.status : ''} />
        )}
        {tab === 'plan' && <PlanTab jobId={job.job_id} />}
      </section>
    </div>
  );
};

export default JobView;