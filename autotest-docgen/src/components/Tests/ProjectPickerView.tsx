/**
 * components/Tests/ProjectPickerView.tsx
 * First popup: the user's projects, each with  [Test]  and  [Tested].
 *   - no projects  -> message + "Create a project" (opens the existing create-project popup)
 *   - read-only role (reviewer) -> only [Tested]
 *   - opened from a row button -> only that project is listed (+ "Show all projects")
 */
import React, { useMemo, useState } from 'react';
import { FolderPlus, History, Loader2, Play, Search } from 'lucide-react';
import { useTestsT } from '../../locales/testsTranslations';
import type { TestsProject } from './TestsModalHost';

interface Props {
  projects: TestsProject[];
  loading: boolean;
  focus: TestsProject | null;
  canGenerate: boolean;
  onTest: (p: TestsProject) => void;
  onTested: (p: TestsProject) => void;
  onCreate: () => void;
  onShowAll: () => void;
}

const SEARCH_FROM = 7;

const ProjectPickerView: React.FC<Props> = ({ projects, loading, focus, canGenerate, onTest, onTested, onCreate, onShowAll }) => {
  const { t } = useTestsT();
  const [query, setQuery] = useState('');

  const list = useMemo(() => {
    if (focus) return [focus];
    const q = query.trim().toLowerCase();
    return q ? projects.filter((p) => p.title.toLowerCase().includes(q)) : projects;
  }, [projects, focus, query]);

  if (loading) {
    return <div className="tp-muted tp-row tp-pad"><Loader2 size={16} className="tp-spin" /> {t('picker.loading')}</div>;
  }

  if (!focus && projects.length === 0) {
    return (
      <div className="tp-emptyblock">
        <FolderPlus size={38} className="tp-muted" />
        <h3>{t('picker.empty.title')}</h3>
        <p className="tp-muted">{t('picker.empty.text')}</p>
        {canGenerate && (
          <button type="button" className="tp-btn tp-btn--primary" onClick={onCreate}>
            <FolderPlus size={16} />{t('picker.empty.cta')}
          </button>
        )}
      </div>
    );
  }

  return (
    <div className="tp-picker">
      <p className="tp-muted tp-intro">{t('picker.intro')}</p>

      {!focus && projects.length >= SEARCH_FROM && (
        <div className="tp-search tp-search--full">
          <Search size={14} />
          <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder={t('picker.search')} aria-label={t('picker.search')} />
        </div>
      )}

      <ul className="tp-plist">
        {list.map((p) => (
          <li key={p.id} className="tp-prow">
            <div className="tp-prow-title" title={p.title}>{p.title}</div>
            <div className="tp-prow-actions">
              {canGenerate && (
                <button type="button" className="tp-btn tp-btn--primary tp-btn--sm" onClick={() => onTest(p)}>
                  <Play size={14} />{t('picker.test')}
                </button>
              )}
              <button type="button" className="tp-btn tp-btn--ghost tp-btn--sm" onClick={() => onTested(p)}>
                <History size={14} />{t('picker.tested')}
              </button>
            </div>
          </li>
        ))}
        {list.length === 0 && <li className="tp-muted tp-pad">{t('picker.noMatch')}</li>}
      </ul>

      {focus && projects.length > 1 && (
        <button type="button" className="tp-link tp-showall" onClick={onShowAll}>{t('picker.showAll')}</button>
      )}
    </div>
  );
};

export default ProjectPickerView;