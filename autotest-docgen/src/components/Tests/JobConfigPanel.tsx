/**
 * components/Tests/JobConfigPanel.tsx
 * ---------------------------------------------------------------------------
 * "New generation job" form:  version  ->  files  ->  levels  ->  Start.
 *
 *  - versions come from  GET /api/upm/projects/{id}/versions/      (already exists)
 *  - files    come from  GET /api/upm/projects/{id}/tree/?version=N (already exists)
 *  - Start    calls      POST /api/analysis/tests/jobs/            (new, Feature 1)
 *
 * Body sent: { project_id (UUID), version_number, paths[] ([] = all files), levels[] }.
 * No snapshot, no unit ids, no integration depth, no "force" (not in the approved API).
 */
import React, { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, FileCode2, FileX2, FlaskConical, Loader2, Play, Search } from 'lucide-react';
import { testsApi, toProblem } from '../../services/testsApi.service';
import { useTestsT } from '../../locales/testsTranslations';
import {
  ALL_LEVELS,
  type ApiProblem,
  type CreateJobResponse,
  type JobSummary,
  type ProjectVersion,
  type TestLevel,
  type TreeFile,
} from '../../types/tests';
import ErrorBanner from './ErrorBanner';

interface Props {
  projectId: string;
  onStarted: (job: CreateJobResponse) => void;
  /** Earlier runs of this project. null = still loading (Start waits); [] = never tested. */
  priorRuns?: JobSummary[] | null;
  /** Lets the "Start a new run?" question offer a shortcut to the earlier results. */
  onViewHistory?: () => void;
}

const isPy = (f: TreeFile) => f.file_type === 'python' || f.filepath.toLowerCase().endsWith('.py');

const JobConfigPanel: React.FC<Props> = ({ projectId, onStarted, priorRuns = [], onViewHistory }) => {
  const { t } = useTestsT();

  const [versions, setVersions] = useState<ProjectVersion[] | null>(null);
  const [version, setVersion] = useState<number | null>(null);
  const [files, setFiles] = useState<TreeFile[]>([]);
  const [filesLoading, setFilesLoading] = useState(false);
  const [scope, setScope] = useState<'all' | 'select'>('all');
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [search, setSearch] = useState('');
  const [levels, setLevels] = useState<Set<TestLevel>>(new Set(ALL_LEVELS));
  const [starting, setStarting] = useState(false);
  const [problem, setProblem] = useState<ApiProblem | null>(null);
  const [confirming, setConfirming] = useState(false);

  // 1) versions
  useEffect(() => {
    let stop = false;
    setVersions(null);
    testsApi
      .getVersions(projectId)
      .then((r) => {
        if (stop) return;
        const sorted = [...r.versions].sort((a, b) => b.version_number - a.version_number);
        setVersions(sorted);
        setVersion(sorted.length ? sorted[0].version_number : null);
      })
      .catch((e) => {
        if (stop) return;
        const p = toProblem(e);
        // "no versions" is a normal empty state (the project has no uploads yet), not an error
        if (p.status === 404) setVersions([]);
        else {
          setVersions([]);
          setProblem(p);
        }
      });
    return () => {
      stop = true;
    };
  }, [projectId]);

  // 2) files of the chosen version
  useEffect(() => {
    if (version === null) {
      setFiles([]);
      return;
    }
    let stop = false;
    setFilesLoading(true);
    setSelected(new Set());
    testsApi
      .getTree(projectId, version)
      .then((r) => {
        if (!stop) setFiles(r.flat_files);
      })
      .catch((e) => {
        if (!stop) {
          setFiles([]);
          setProblem(toProblem(e));
        }
      })
      .finally(() => {
        if (!stop) setFilesLoading(false);
      });
    return () => {
      stop = true;
    };
  }, [projectId, version]);

  const pyFiles = useMemo(() => files.filter(isPy), [files]);
  const visible = useMemo(() => {
    const q = search.trim().toLowerCase();
    return q ? files.filter((f) => f.filepath.toLowerCase().includes(q)) : files;
  }, [files, search]);

  const levelCount = levels.size;
  const fileCount = scope === 'all' ? pyFiles.length : selected.size;

  const validation: string | null =
    pyFiles.length === 0 ? t('config.noPython')
    : levelCount === 0 ? t('config.needLevel')
    : scope === 'select' && selected.size === 0 ? t('config.needFiles')
    : null;

  const toggleFile = (path: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });

  const toggleLevel = (level: TestLevel) =>
    setLevels((prev) => {
      const next = new Set(prev);
      if (next.has(level)) next.delete(level);
      else next.add(level);
      return next;
    });

  const priorCount = priorRuns?.length ?? 0;
  const showConfirm = confirming && !validation;

  // First press on a project that was tested before only asks the question.
  const onStartClick = () => {
    if (validation || starting || version === null) return;
    if (priorCount > 0 && !confirming) {
      setConfirming(true);
      return;
    }
    void start();
  };

  const start = async () => {
    if (validation || starting || version === null) return;
    setConfirming(false);
    setStarting(true);
    setProblem(null);
    try {
      const res = await testsApi.createJob({
        project_id: projectId,
        version_number: version,
        paths: scope === 'all' ? [] : Array.from(selected),
        levels: ALL_LEVELS.filter((l) => levels.has(l)),
      });
      onStarted(res);
    } catch (e) {
      setProblem(toProblem(e));
    } finally {
      setStarting(false);
    }
  };

  // ── render ────────────────────────────────────────────────────────────
  if (versions === null) {
    return (
      <section className="tp-card tp-config">
        <div className="tp-card-title"><FlaskConical size={18} />{t('config.title')}</div>
        <div className="tp-muted tp-row"><Loader2 size={16} className="tp-spin" /> {t('config.loadingVersions')}</div>
      </section>
    );
  }

  if (versions.length === 0) {
    return (
      <section className="tp-card tp-config">
        <div className="tp-card-title"><FlaskConical size={18} />{t('config.title')}</div>
        <ErrorBanner problem={problem} onDismiss={() => setProblem(null)} />
        <div className="tp-muted">{t('config.noVersions')}</div>
      </section>
    );
  }

  return (
    <section className="tp-card tp-config">
      <div className="tp-card-title"><FlaskConical size={18} />{t('config.title')}</div>

      {/* Version */}
      <label className="tp-label" htmlFor="tp-version">{t('config.version')}</label>
      <select
        id="tp-version"
        className="tp-input"
        value={version ?? ''}
        onChange={(e) => setVersion(Number(e.target.value))}
      >
        {versions.map((v, i) => (
          <option key={v.version_number} value={v.version_number}>
            {t('config.versionOption', {
              v: v.version_number,
              latest: i === 0 ? t('config.latest') : '',
              files: v.total_files,
            })}
          </option>
        ))}
      </select>

      {/* Files */}
      <div className="tp-label tp-mt">{t('config.files')}</div>
      <div className="tp-segment" role="radiogroup">
        <button type="button" role="radio" aria-checked={scope === 'all'} className={scope === 'all' ? 'is-active' : ''} onClick={() => setScope('all')}>
          {t('config.scopeAll')}
        </button>
        <button type="button" role="radio" aria-checked={scope === 'select'} className={scope === 'select' ? 'is-active' : ''} onClick={() => setScope('select')}>
          {t('config.scopeSelect')}
        </button>
      </div>

      {scope === 'select' && (
        <div className="tp-filelist">
          <div className="tp-filelist-tools">
            <div className="tp-search">
              <Search size={14} />
              <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder={t('config.search')} />
            </div>
            <button type="button" className="tp-link" onClick={() => setSelected(new Set(pyFiles.map((f) => f.filepath)))}>
              {t('config.selectAll')}
            </button>
            <button type="button" className="tp-link" onClick={() => setSelected(new Set())}>
              {t('config.clear')}
            </button>
          </div>

          <div className="tp-filelist-body">
            {filesLoading && <div className="tp-muted tp-row"><Loader2 size={14} className="tp-spin" /> {t('common.loading')}</div>}
            {!filesLoading && visible.length === 0 && <div className="tp-muted">{t('config.noFiles')}</div>}
            {visible.map((f) => {
              const py = isPy(f);
              return (
                <label key={f.file_id} className={`tp-fileitem ${py ? '' : 'is-disabled'}`}>
                  <input
                    type="checkbox"
                    disabled={!py}
                    checked={selected.has(f.filepath)}
                    onChange={() => toggleFile(f.filepath)}
                  />
                  {py ? <FileCode2 size={15} /> : <FileX2 size={15} />}
                  <span className="tp-filepath" title={f.filepath}>{f.filepath}</span>
                  {!py ? (
                    <span className="tp-tag">{t('config.pythonOnly')}</span>
                  ) : (
                    <span className={`tp-tag ${f.status === 'unchanged' ? '' : 'tp-tag--accent'}`}>
                      {f.status === 'unchanged' ? t('file.unchanged') : t('file.new')}
                    </span>
                  )}
                </label>
              );
            })}
          </div>
          <div className="tp-muted tp-small">{t('config.selected', { n: selected.size, m: pyFiles.length })}</div>
        </div>
      )}

      {/* Levels */}
      <div className="tp-label tp-mt">{t('config.levels')}</div>
      <div className="tp-levels">
        {ALL_LEVELS.map((lvl) => (
          <label key={lvl} className={`tp-level ${levels.has(lvl) ? 'is-on' : ''}`}>
            <input type="checkbox" checked={levels.has(lvl)} onChange={() => toggleLevel(lvl)} />
            <div>
              <div className="tp-level-name">{t(`config.level.${lvl}` as 'config.level.unit')}</div>
              <div className="tp-muted tp-small">{t(`config.level.${lvl}.desc` as 'config.level.unit.desc')}</div>
            </div>
          </label>
        ))}
      </div>

      <ErrorBanner problem={problem} onDismiss={() => setProblem(null)} />

      {validation && <div className="tp-hint">{validation}</div>}
      {!validation && (
        <div className="tp-muted tp-small">
          {scope === 'all'
            ? t('config.summaryAll', { levels: levelCount })
            : t('config.summarySome', { files: fileCount, levels: levelCount })}
        </div>
      )}

      {showConfirm ? (
        <div className="tp-confirm" role="alertdialog" aria-labelledby="tp-confirm-title">
          <div id="tp-confirm-title" className="tp-confirm-title"><AlertTriangle size={16} />{t('confirm.title')}</div>
          <p className="tp-muted">{t('confirm.text', { n: priorCount })}</p>
          <div className="tp-actions">
            <button type="button" className="tp-btn tp-btn--primary" disabled={starting} onClick={() => void start()}>
              {starting ? <Loader2 size={16} className="tp-spin" /> : <Play size={16} />}
              {t('confirm.yes')}
            </button>
            {onViewHistory && (
              <button type="button" className="tp-btn tp-btn--ghost" onClick={onViewHistory}>{t('confirm.view')}</button>
            )}
            <button type="button" className="tp-btn tp-btn--ghost" onClick={() => setConfirming(false)}>{t('confirm.back')}</button>
          </div>
        </div>
      ) : (
        <button
          type="button"
          className="tp-btn tp-btn--primary tp-btn--block"
          disabled={!!validation || starting || priorRuns === null}
          onClick={onStartClick}
        >
          {starting || priorRuns === null ? <Loader2 size={16} className="tp-spin" /> : <Play size={16} />}
          {starting ? t('config.starting') : t('config.start')}
        </button>
      )}
    </section>
  );
};

export default JobConfigPanel;