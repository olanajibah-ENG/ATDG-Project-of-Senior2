/**
 * components/Tests/badges.tsx
 * Small presentational pieces shared by the Test Generation screens.
 */
import React from 'react';
import { AlertTriangle, Check, Clock, Loader2, Minus, X } from 'lucide-react';
import { useTestsT } from '../../locales/testsTranslations';

/** Maps any back-end status string to a colour family (unknown -> neutral). */
const tone = (status: string): 'ok' | 'bad' | 'warn' | 'muted' | 'info' | 'busy' => {
  switch (status) {
    case 'ready':
    case 'completed':
      return 'ok';
    case 'generation_failed':
    case 'failed':
      return 'bad';
    case 'test_failed':
    case 'environment_error':
    case 'completed_with_issues':
    case 'partial':
      return 'warn';
    case 'skipped':
    case 'cancelled':
      return 'muted';
    case 'running':
      return 'busy';
    default:
      return 'info'; // pending / unknown
  }
};

export const StatusBadge: React.FC<{ status: string }> = ({ status }) => {
  const { label } = useTestsT();
  return (
    <span className={`tp-badge tp-badge--${tone(status)}`}>
      {status === 'running' && <Loader2 size={12} className="tp-spin" />}
      {label('status', status)}
    </span>
  );
};

/** One compact cell for a (file x level) status. */
export const LevelPill: React.FC<{ status?: string }> = ({ status }) => {
  const { label, short } = useTestsT();
  if (!status) return <span className="tp-dash">—</span>;
  const icon =
    status === 'ready' ? <Check size={13} /> :
    status === 'pending' ? <Clock size={13} /> :
    status === 'skipped' ? <Minus size={13} /> :
    status === 'generation_failed' ? <X size={13} /> :
    <AlertTriangle size={13} />;
  return (
    <span className={`tp-pill tp-pill--${tone(status)}`} title={label('status', status)}>
      {icon}
      <span className="tp-pill-text">{short(status)}</span>
    </span>
  );
};