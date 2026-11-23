/**
 * components/Tests/format.ts
 * Small display helpers shared by the Tests modals.
 */
/** "12 Nov 2026, 14:30" in the UI language; "—" when the date is unknown or invalid. */
export const formatWhen = (iso: string | null | undefined, language: string): string => {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '—';
  return d.toLocaleString(language === 'ar' ? 'ar' : 'en-GB', { dateStyle: 'medium', timeStyle: 'short' });
};