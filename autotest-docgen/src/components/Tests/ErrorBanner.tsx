/**
 * components/Tests/ErrorBanner.tsx
 * Shows an ApiProblem with a friendly, translated message.
 * The raw `code` is shown as a small tag so it is easy to report to the back-end developer.
 */
import React from 'react';
import { AlertCircle, X } from 'lucide-react';
import { useTestsT } from '../../locales/testsTranslations';
import type { ApiProblem } from '../../types/tests';

interface Props {
  problem: ApiProblem | null;
  onRetry?: () => void;
  onDismiss?: () => void;
}

const ErrorBanner: React.FC<Props> = ({ problem, onRetry, onDismiss }) => {
  const { t } = useTestsT();
  if (!problem) return null;

  // known codes have a translated sentence ("err.<code>"); anything else gets the generic one
  const key = `err.${problem.code}` as Parameters<typeof t>[0];
  const translated = t(key);
  const text = translated === key ? t('err.unknown') : translated;

  return (
    <div className="tp-alert tp-alert--error" role="alert">
      <AlertCircle size={18} className="tp-alert-icon" />
      <div className="tp-alert-body">
        <div>{text}</div>
        <div className="tp-alert-meta">
          <code>{problem.code}</code>
          {problem.status > 0 && <code>HTTP {problem.status}</code>}
        </div>
      </div>
      <div className="tp-alert-actions">
        {onRetry && (
          <button type="button" className="tp-btn tp-btn--ghost tp-btn--sm" onClick={onRetry}>
            {t('common.retry')}
          </button>
        )}
        {onDismiss && (
          <button type="button" className="tp-icon-btn" onClick={onDismiss} aria-label={t('common.dismiss')}>
            <X size={16} />
          </button>
        )}
      </div>
    </div>
  );
};

export default ErrorBanner;