/**
 * components/Tests/TestsModalHost.tsx
 * ---------------------------------------------------------------------------
 * The whole Feature 1 UI as popups, mounted once in Dashboard.tsx:
 *
 *   picker  -> list of my projects, each [Test] [Tested]
 *   newRun  -> version / files / levels form  (asks "Start a new run?" if tested before)
 *   history -> earlier runs of the project ("Tested")
 *   job     -> progress + results (Files | Tests | Coverage | Plan), download, cancel
 *
 * Dashboard mounts it only while open ({request && <TestsModalHost .../>}), so every
 * opening starts clean. Reviewer = read-only: [Test] and Cancel are hidden
 * (this rule is a proposal, not part of the approved plan).
 */
import React, { useCallback, useContext, useState } from 'react';
import { Info } from 'lucide-react';
import { AuthContext } from '../../context/AuthContext';
import { USE_TESTS_MOCK } from '../../services/testsApi.service';
import { useTestsT } from '../../locales/testsTranslations';
import type { CreateJobResponse } from '../../types/tests';
import ModalShell from './ModalShell';
import ProjectPickerView from './ProjectPickerView';
import NewRunView from './NewRunView';
import HistoryView from './HistoryView';
import JobView from './JobView';

export interface TestsProject {
  id: string;
  title: string;
}

export type TestsRequest =
  | { view: 'picker'; project?: TestsProject | null }
  | { view: 'newRun'; project: TestsProject }
  | { view: 'job'; projectId: string; jobId: string };

/** Roles that may only look at results. */
const READ_ONLY_ROLES = ['reviewer'];

type Screen =
  | { name: 'picker' }
  | { name: 'newRun'; project: TestsProject }
  | { name: 'history'; project: TestsProject }
  | { name: 'job'; projectId: string; jobId: string };

interface Props {
  request: TestsRequest;
  projects: TestsProject[];
  projectsLoading: boolean;
  onClose: () => void;
  /** Closes this popup and opens the existing "create project" popup. */
  onCreateProject: () => void;
}

const TestsModalHost: React.FC<Props> = ({ request, projects, projectsLoading, onClose, onCreateProject }) => {
  const { t } = useTestsT();
  const { user } = useContext(AuthContext);
  const role = user?.profile?.role?.role_name?.toLowerCase() ?? '';
  const canGenerate = !READ_ONLY_ROLES.includes(role);

  const [focus, setFocus] = useState<TestsProject | null>(
    request.view === 'picker' ? request.project ?? null : request.view === 'newRun' ? request.project : null,
  );
  const [screen, setScreen] = useState<Screen>(
    request.view === 'job'
      ? { name: 'job', projectId: request.projectId, jobId: request.jobId }
      : request.view === 'newRun'
        ? { name: 'newRun', project: request.project }
        : { name: 'picker' },
  );

  const findProject = useCallback(
    (id: string): TestsProject | null => projects.find((p) => p.id === id) ?? (focus && focus.id === id ? focus : null),
    [projects, focus],
  );

  const openHistory = (project: TestsProject) => setScreen({ name: 'history', project });
  const openJob = (projectId: string, jobId: string) => setScreen({ name: 'job', projectId, jobId });
  const toPicker = () => setScreen({ name: 'picker' });

  let title = t('picker.title');
  let subtitle: string | undefined;
  let size: 'sm' | 'md' | 'lg' = 'sm';
  let onBack: (() => void) | undefined;
  let body: React.ReactNode = null;

  switch (screen.name) {
    case 'picker':
      body = (
        <ProjectPickerView
          projects={projects}
          loading={projectsLoading}
          focus={focus}
          canGenerate={canGenerate}
          onTest={(p) => setScreen({ name: 'newRun', project: p })}
          onTested={openHistory}
          onCreate={onCreateProject}
          onShowAll={() => setFocus(null)}
        />
      );
      break;

    case 'newRun':
      title = t('newRun.title');
      subtitle = screen.project.title;
      size = 'md';
      onBack = toPicker;
      body = (
        <NewRunView
          project={screen.project}
          onStarted={(res: CreateJobResponse) => openJob(screen.project.id, res.job_id)}
          onViewHistory={() => openHistory(screen.project)}
          onOpenJob={(id) => openJob(screen.project.id, id)}
        />
      );
      break;

    case 'history':
      title = t('history.title');
      subtitle = screen.project.title;
      size = 'md';
      onBack = toPicker;
      body = (
        <HistoryView
          project={screen.project}
          canGenerate={canGenerate}
          onOpen={(id) => openJob(screen.project.id, id)}
          onNewRun={() => setScreen({ name: 'newRun', project: screen.project })}
        />
      );
      break;

    case 'job': {
      const project = findProject(screen.projectId);
      title = t('job.modalTitle');
      subtitle = project?.title;
      size = 'lg';
      onBack = project ? () => openHistory(project) : toPicker;
      body = <JobView key={screen.jobId} projectId={screen.projectId} jobId={screen.jobId} canGenerate={canGenerate} />;
      break;
    }
  }

  return (
    <ModalShell title={title} subtitle={subtitle} size={size} onClose={onClose} onBack={onBack}>
      {USE_TESTS_MOCK && (
        <div className="tp-banner tp-banner--demo">
          <Info size={16} />
          <div className="tp-banner-body tp-small">{t('page.mockBanner')}</div>
        </div>
      )}
      {body}
    </ModalShell>
  );
};

export default TestsModalHost;