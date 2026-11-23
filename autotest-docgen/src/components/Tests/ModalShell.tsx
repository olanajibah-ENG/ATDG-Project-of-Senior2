/**
 * components/Tests/ModalShell.tsx
 * ---------------------------------------------------------------------------
 * The one popup frame used by every Tests screen (project list, new run,
 * history, results). Close = X button or Esc. A click on the dark backdrop does
 * NOT close it, so a half-filled form is never lost by accident.
 *
 * It must be rendered INSIDE the Dashboard root (.dashboard.light / .dark) so the
 * light/dark tokens of .tp-root apply.
 */
import React, { useEffect, useRef, type ReactNode } from 'react';
import { ArrowLeft, ArrowRight, FlaskConical, X } from 'lucide-react';
import { useTestsT } from '../../locales/testsTranslations';
import '../../ProjectTestsPage.css';

interface Props {
  title: string;
  subtitle?: string;
  size?: 'sm' | 'md' | 'lg';
  onClose: () => void;
  onBack?: () => void;
  children: ReactNode;
}

const ModalShell: React.FC<Props> = ({ title, subtitle, size = 'md', onClose, onBack, children }) => {
  const { t, isRTL } = useTestsT();
  const dialogRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose; // always the latest handler, without re-running the effect below

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') closeRef.current();
    };
    document.addEventListener('keydown', onKey);
    const previous = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    dialogRef.current?.focus();
    return () => {
      document.removeEventListener('keydown', onKey);
      document.body.style.overflow = previous;
    };
  }, []);

  const BackIcon = isRTL ? ArrowRight : ArrowLeft;

  return (
    <div className="tp-root tp-overlay">
      <div ref={dialogRef} tabIndex={-1} className={`tp-modal tp-modal--${size}`} role="dialog" aria-modal="true" aria-label={title}>
        <header className="tp-modal-head">
          {onBack && (
            <button type="button" className="tp-icon-btn" onClick={onBack} aria-label={t('modal.back')} title={t('modal.back')}>
              <BackIcon size={18} />
            </button>
          )}
          <div className="tp-modal-titlebox">
            <h2 className="tp-modal-title"><FlaskConical size={18} />{title}</h2>
            {subtitle && <div className="tp-muted tp-small tp-modal-sub">{subtitle}</div>}
          </div>
          <button type="button" className="tp-icon-btn" onClick={onClose} aria-label={t('modal.close')} title={t('modal.close')}>
            <X size={18} />
          </button>
        </header>
        <div className="tp-modal-body">{children}</div>
      </div>
    </div>
  );
};

export default ModalShell;