/**
 * components/Tests/FilesProgressTable.tsx
 * Per-file progress: one row per file, one column per test level (unit / edge / integration).
 * Data = `files[]` of GET /jobs/{id}/ (the UI is file-centric by design).
 */
import React from 'react';
import { useTestsT } from '../../locales/testsTranslations';
import { ALL_LEVELS, type JobFile } from '../../types/tests';
import { LevelPill, StatusBadge } from './badges';

const FilesProgressTable: React.FC<{ files: JobFile[] }> = ({ files }) => {
  const { t, label } = useTestsT();

  if (files.length === 0) return <div className="tp-empty">{t('files.empty')}</div>;

  return (
    <div className="tp-tablewrap">
      <table className="tp-table">
        <thead>
          <tr>
            <th>{t('files.file')}</th>
            <th>{t('files.status')}</th>
            {ALL_LEVELS.map((l) => (
              <th key={l}>{t(`level.${l}` as 'level.unit')}</th>
            ))}
            <th>{t('files.notes')}</th>
          </tr>
        </thead>
        <tbody>
          {files.map((f) => (
            <tr key={f.path}>
              <td><span className="tp-filepath" title={f.path}>{f.path}</span></td>
              <td><StatusBadge status={f.status} /></td>
              {ALL_LEVELS.map((l) => (
                <td key={l}>{f.status === 'skipped' ? <span className="tp-dash">—</span> : <LevelPill status={f.levels?.[l]} />}</td>
              ))}
              <td className="tp-muted">{f.reason ? label('reason', f.reason) : ''}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};

export default FilesProgressTable;