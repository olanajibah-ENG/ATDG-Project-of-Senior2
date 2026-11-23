/**
 * locales/testsTranslations.ts
 * ---------------------------------------------------------------------------
 * English + Arabic strings for the Test Generation pages.
 * Kept in its own file so the big translations.ts is not touched.
 *
 * Usage:  const { t, label } = useTestsT();
 *   t('config.start')                       -> plain key
 *   t('job.progress', { done: 3, total: 9 })-> {placeholders}
 *   label('status', 'ready')                -> status.ready, or a humanized fallback
 *                                              (so a NEW back-end value never breaks the UI)
 */
import { useCallback } from 'react';
import { useLanguage } from '../context/LanguageContext';

const en = {
  // page
  'page.title': 'Test Generation',
  'page.subtitle': 'Generate trusted tests for a project version and review how they ran.',
  'page.back': '← Dashboard',
  'page.trustNote':
    'A test is marked "ready" only after it runs cleanly in an isolated sandbox. Tests that were not executed are never delivered.',
  'page.mockBanner': 'Demo mode: the data on this page is simulated (VITE_TESTS_MOCK=true).',
  'page.readOnly': 'Read-only access: reviewers can open and inspect jobs, but cannot start or cancel generation.',
  'nav.projects': 'Projects',
  'nav.generatedFiles': 'Generated Files',
  'nav.testJobs': 'Test Generation',

  // config panel
  'config.title': 'New generation job',
  'config.version': 'Project version',
  'config.versionOption': 'Version {v}{latest} · {files} files',
  'config.latest': ' (latest)',
  'config.loadingVersions': 'Loading versions…',
  'config.noVersions': 'No uploaded versions yet. Upload files to this project first.',
  'config.files': 'Files',
  'config.scopeAll': 'All Python files in this version',
  'config.scopeSelect': 'Select files',
  'config.search': 'Search files…',
  'config.selectAll': 'Select all',
  'config.clear': 'Clear',
  'config.selected': '{n} of {m} selected',
  'config.pythonOnly': 'Python only',
  'config.noFiles': 'No files in this version.',
  'config.noPython': 'This version has no Python files, so there is nothing to generate.',
  'config.levels': 'Test levels',
  'config.level.unit': 'Unit',
  'config.level.unit.desc': 'One function or method at a time.',
  'config.level.edge': 'Edge',
  'config.level.edge.desc': 'Boundaries, empty values and exceptions.',
  'config.level.integration': 'Integration',
  'config.level.integration.desc': 'Small groups of related units (depth ≤ 2, up to 4 units).',
  'config.summaryAll': 'All Python files · {levels} level(s)',
  'config.summarySome': '{files} file(s) · {levels} level(s)',
  'config.needLevel': 'Select at least one test level.',
  'config.needFiles': 'Select at least one Python file, or use all files.',
  'config.start': 'Start generation',
  'config.starting': 'Starting…',
  'file.new': 'new / modified',
  'file.unchanged': 'unchanged',

  // job card
  'job.label': 'Job',
  'job.version': 'Version {v}',
  'job.stage': 'Stage',
  'job.progress': '{done} of {total} tests processed',
  'job.preparing': 'Preparing…',
  'job.cancel': 'Cancel job',
  'job.cancelling': 'Cancelling…',
  'job.download': 'Download ready tests',
  'job.downloading': 'Preparing ZIP…',
  'job.downloadHint': 'Available when the job has finished and has at least one ready test.',
  'job.refresh': 'Refresh',
  'job.copyLink': 'Copy link',
  'job.copied': 'Copied',
  'job.summary.completed': 'All tests were generated and passed in the sandbox.',
  'job.summary.completed_with_issues': 'Finished with issues: some tests are not ready (see the details below).',
  'job.summary.failed': 'The job failed.',
  'job.summary.cancelled': 'The job was cancelled. Tests that were already ready can still be downloaded.',
  'job.empty.title': 'No job selected',
  'job.empty.text': 'Set up a job on the left and start it. Progress and results will appear here.',
  'job.empty.readonly': 'You can inspect a job that was shared with you by entering its ID.',
  'job.openById': 'Open a job by ID',
  'job.openPlaceholder': 'job_…',
  'job.open': 'Open',
  'job.notFound': 'This job was not found.',
  'job.loading': 'Loading job…',

  // tabs
  'tabs.files': 'Files',
  'tabs.records': 'Tests',
  'tabs.coverage': 'Coverage',
  'tabs.plan': 'Plan',

  // files table
  'files.file': 'File',
  'files.status': 'Status',
  'files.notes': 'Notes',
  'files.empty': 'The file list appears once the job has been planned.',
  'level.unit': 'Unit',
  'level.edge': 'Edge',
  'level.integration': 'Integration',

  // records
  'records.all': 'All',
  'records.status': 'Status',
  'records.level': 'Level',
  'records.file': 'File',
  'records.unit': 'Unit',
  'records.reason': 'Reason',
  'records.testFile': 'Test file',
  'records.showing': 'Showing {n} of {total}',
  'records.empty': 'No tests match these filters.',
  'records.prev': 'Previous',
  'records.next': 'Next',

  // coverage
  'coverage.line': 'Line coverage',
  'coverage.branch': 'Branch coverage',
  'coverage.file': 'File',
  'coverage.lines': 'Lines',
  'coverage.branches': 'Branches',
  'coverage.missing': 'Missing lines',
  'coverage.more': '+{n} more',
  'coverage.none': 'Coverage appears when the final run of the ready tests has finished.',
  'coverage.note': 'Measured on the final all-pass run of ready tests. Reported per file.',
  'coverage.noFiles': 'No coverage data: there are no ready tests.',

  // plan
  'plan.workItems': 'Work items',
  'plan.units': 'Units to test',
  'plan.skipped': 'Skipped files',
  'plan.unit': 'Unit',
  'plan.file': 'File',
  'plan.kind': 'Kind',
  'plan.none': 'The plan is not available yet.',
  'plan.noSkipped': 'No skipped files.',

  // statuses
  'status.pending': 'Pending',
  'status.running': 'Running',
  'status.completed': 'Completed',
  'status.completed_with_issues': 'Completed with issues',
  'status.failed': 'Failed',
  'status.cancelled': 'Cancelled',
  'status.ready': 'Ready',
  'status.partial': 'Partial',
  'status.skipped': 'Skipped',
  'status.generation_failed': 'Generation failed',
  'status.environment_error': 'Environment error',
  'status.test_failed': 'Test failed',

  // short labels used inside narrow table cells (fallback: status.*)
  'pill.generation_failed': 'Gen. failed',
  'pill.environment_error': 'Env. error',
  'pill.test_failed': 'Test failed',

  // stages (EXAMPLES: the real list is not final)
  'stage.queued': 'Queued',
  'stage.checking_analysis': 'Checking analysis',
  'stage.planning': 'Planning',
  'stage.generating': 'Generating tests',
  'stage.validating': 'Validating',
  'stage.running_sandbox': 'Running in sandbox',
  'stage.accepting': 'Final verification',
  'stage.done': 'Done',

  // reasons (EXAMPLES: the real list is not final)
  'reason.unsupported_language': 'Unsupported language',
  'reason.invalid_after_repair': 'Still invalid after repair attempts',
  'reason.assertion_failed': 'Assertions failed',
  'reason.no_units': 'No testable functions',
  'reason.syntax_error': 'Syntax error in source',

  // errors
  'err.validation_error': 'The request is not valid. Check the version, files and levels.',
  'err.unauthorized': 'Your session has expired. Please log in again.',
  'err.forbidden': 'You do not have permission for this action.',
  'err.not_found': 'Not found.',
  'err.analysis_missing': 'Analysis of this version is not finished yet. Wait a moment, then try again.',
  'err.no_python_files': 'The selection contains no Python files.',
  'err.no_ready_tests': 'There are no ready tests to download yet.',
  'err.coverage_not_ready': 'Coverage is not ready yet.',
  'err.conflict': 'This action is not possible in the job’s current state.',
  'err.network': 'Cannot reach the server. Check your connection and try again.',
  'err.unknown': 'Something went wrong. Please try again.',
  'common.retry': 'Retry',
  'common.dismiss': 'Dismiss',
  'common.loading': 'Loading…',

  // modal flow (Dashboard -> Tests)
  'modal.close': 'Close',
  'modal.back': 'Back',
  'picker.title': 'Generate tests',
  'picker.intro': 'Choose a project: start a new test run, or review the runs done before.',
  'picker.loading': 'Loading your projects…',
  'picker.empty.title': 'You don’t have any projects yet',
  'picker.empty.text': 'Create a project and upload its code first. Then you can generate tests for it.',
  'picker.empty.cta': 'Create a project',
  'picker.search': 'Search projects…',
  'picker.noMatch': 'No project matches your search.',
  'picker.test': 'Test',
  'picker.tested': 'Tested',
  'picker.showAll': 'Show all projects',
  'newRun.title': 'New test run',
  'newRun.prior.title': 'This project was tested before',
  'newRun.prior.last': 'Last run: {when} · Version {v} · {status}',
  'newRun.prior.view': 'View previous results',
  'newRun.running.title': 'A run is still in progress',
  'newRun.running.open': 'Open it',
  'confirm.title': 'Start a new run?',
  'confirm.text': 'This project already has {n} earlier run(s). A new run starts from scratch, uses AI requests, and does not replace the old results: they stay under “Tested”.',
  'confirm.yes': 'Yes, start a new run',
  'confirm.view': 'View previous results',
  'confirm.back': 'Back',
  'history.title': 'Tested',
  'history.subtitle': 'Earlier test runs of this project',
  'history.empty.title': 'No tests yet',
  'history.empty.text': 'Nothing has been generated for this project so far.',
  'history.empty.cta': 'Start a test',
  'history.new': 'New test run',
  'history.version': 'Version {v}',
  'history.tests': '{done} / {total} tests',
  'history.ready': '{n} ready',
  'history.localNote': 'This list is kept in this browser only. It becomes complete on any device once the server provides run history.',
  'history.openById': 'Open by job ID',
  'job.modalTitle': 'Test run',
  'job.fromHistory': 'Back to “Tested”',
};

type Key = keyof typeof en;

const ar: Record<Key, string> = {
  'page.title': 'توليد الاختبارات',
  'page.subtitle': 'ولّد اختبارات موثوقة لإصدار من المشروع وراجع نتائج تشغيلها.',
  'page.back': '← لوحة التحكم',
  'page.trustNote':
    'لا يُعلَّم الاختبار بأنه «جاهز» إلا بعد أن يعمل بنجاح داخل بيئة معزولة. الاختبارات التي لم تُنفَّذ لا تُسلَّم أبداً.',
  'page.mockBanner': 'وضع تجريبي: البيانات في هذه الصفحة محاكاة (VITE_TESTS_MOCK=true).',
  'page.readOnly': 'صلاحية قراءة فقط: يستطيع المراجع فتح المهام ومعاينتها، لكن لا يستطيع بدء التوليد أو إلغاءه.',
  'nav.projects': 'المشاريع',
  'nav.generatedFiles': 'الملفات المُنشأة',
  'nav.testJobs': 'توليد الاختبارات',

  'config.title': 'مهمة توليد جديدة',
  'config.version': 'إصدار المشروع',
  'config.versionOption': 'الإصدار {v}{latest} · {files} ملف',
  'config.latest': ' (الأحدث)',
  'config.loadingVersions': 'جاري تحميل الإصدارات…',
  'config.noVersions': 'لا توجد إصدارات مرفوعة بعد. ارفع ملفات إلى هذا المشروع أولاً.',
  'config.files': 'الملفات',
  'config.scopeAll': 'كل ملفات Python في هذا الإصدار',
  'config.scopeSelect': 'اختيار ملفات',
  'config.search': 'ابحث في الملفات…',
  'config.selectAll': 'تحديد الكل',
  'config.clear': 'مسح',
  'config.selected': 'تم اختيار {n} من {m}',
  'config.pythonOnly': 'Python فقط',
  'config.noFiles': 'لا توجد ملفات في هذا الإصدار.',
  'config.noPython': 'لا يحتوي هذا الإصدار على ملفات Python، فلا يوجد ما يمكن توليده.',
  'config.levels': 'مستويات الاختبار',
  'config.level.unit': 'وحدة (Unit)',
  'config.level.unit.desc': 'دالة أو method واحدة في كل مرة.',
  'config.level.edge': 'حالات حدّية (Edge)',
  'config.level.edge.desc': 'الحدود والقيم الفارغة والاستثناءات.',
  'config.level.integration': 'تكامل (Integration)',
  'config.level.integration.desc': 'مجموعات صغيرة من الوحدات المترابطة (عمق ≤ 2، حتى 4 وحدات).',
  'config.summaryAll': 'كل ملفات Python · {levels} مستوى',
  'config.summarySome': '{files} ملف · {levels} مستوى',
  'config.needLevel': 'اختر مستوى اختبار واحداً على الأقل.',
  'config.needFiles': 'اختر ملف Python واحداً على الأقل، أو استخدم كل الملفات.',
  'config.start': 'ابدأ التوليد',
  'config.starting': 'جاري البدء…',
  'file.new': 'جديد / معدّل',
  'file.unchanged': 'دون تغيير',

  'job.label': 'المهمة',
  'job.version': 'الإصدار {v}',
  'job.stage': 'المرحلة',
  'job.progress': 'تمت معالجة {done} من {total} اختباراً',
  'job.preparing': 'جاري التحضير…',
  'job.cancel': 'إلغاء المهمة',
  'job.cancelling': 'جاري الإلغاء…',
  'job.download': 'تنزيل الاختبارات الجاهزة',
  'job.downloading': 'جاري تجهيز الملف…',
  'job.downloadHint': 'متاح عند انتهاء المهمة ووجود اختبار جاهز واحد على الأقل.',
  'job.refresh': 'تحديث',
  'job.copyLink': 'نسخ الرابط',
  'job.copied': 'تم النسخ',
  'job.summary.completed': 'تم توليد كل الاختبارات ونجحت داخل البيئة المعزولة.',
  'job.summary.completed_with_issues': 'انتهت مع ملاحظات: بعض الاختبارات غير جاهزة (التفاصيل بالأسفل).',
  'job.summary.failed': 'فشلت المهمة.',
  'job.summary.cancelled': 'أُلغيت المهمة. الاختبارات التي أصبحت جاهزة قبل الإلغاء ما زال تنزيلها ممكناً.',
  'job.empty.title': 'لا توجد مهمة محددة',
  'job.empty.text': 'جهّز مهمة من اللوحة على اليسار وابدأها. سيظهر التقدّم والنتائج هنا.',
  'job.empty.readonly': 'يمكنك معاينة مهمة شُورِكت معك بإدخال معرّفها.',
  'job.openById': 'افتح مهمة بالمعرّف',
  'job.openPlaceholder': 'job_…',
  'job.open': 'فتح',
  'job.notFound': 'لم يتم العثور على هذه المهمة.',
  'job.loading': 'جاري تحميل المهمة…',

  'tabs.files': 'الملفات',
  'tabs.records': 'الاختبارات',
  'tabs.coverage': 'التغطية',
  'tabs.plan': 'الخطة',

  'files.file': 'الملف',
  'files.status': 'الحالة',
  'files.notes': 'ملاحظات',
  'files.empty': 'تظهر قائمة الملفات بعد تخطيط المهمة.',
  'level.unit': 'وحدة',
  'level.edge': 'حدّية',
  'level.integration': 'تكامل',

  'records.all': 'الكل',
  'records.status': 'الحالة',
  'records.level': 'المستوى',
  'records.file': 'الملف',
  'records.unit': 'الوحدة',
  'records.reason': 'السبب',
  'records.testFile': 'ملف الاختبار',
  'records.showing': 'عرض {n} من {total}',
  'records.empty': 'لا توجد اختبارات مطابقة لهذه المرشحات.',
  'records.prev': 'السابق',
  'records.next': 'التالي',

  'coverage.line': 'تغطية الأسطر',
  'coverage.branch': 'تغطية الفروع',
  'coverage.file': 'الملف',
  'coverage.lines': 'الأسطر',
  'coverage.branches': 'الفروع',
  'coverage.missing': 'الأسطر غير المغطاة',
  'coverage.more': '+{n} أخرى',
  'coverage.none': 'تظهر التغطية عند انتهاء التشغيل النهائي للاختبارات الجاهزة.',
  'coverage.note': 'تُقاس في التشغيل النهائي الناجح للاختبارات الجاهزة، وتُعرض لكل ملف.',
  'coverage.noFiles': 'لا توجد بيانات تغطية: لا توجد اختبارات جاهزة.',

  'plan.workItems': 'عناصر العمل',
  'plan.units': 'الوحدات المراد اختبارها',
  'plan.skipped': 'الملفات المتخطّاة',
  'plan.unit': 'الوحدة',
  'plan.file': 'الملف',
  'plan.kind': 'النوع',
  'plan.none': 'الخطة غير متاحة بعد.',
  'plan.noSkipped': 'لا توجد ملفات متخطّاة.',

  'status.pending': 'قيد الانتظار',
  'status.running': 'قيد التنفيذ',
  'status.completed': 'مكتملة',
  'status.completed_with_issues': 'مكتملة مع ملاحظات',
  'status.failed': 'فشلت',
  'status.cancelled': 'ملغاة',
  'status.ready': 'جاهز',
  'status.partial': 'جزئي',
  'status.skipped': 'متخطّى',
  'status.generation_failed': 'فشل التوليد',
  'status.environment_error': 'خطأ في البيئة',
  'status.test_failed': 'فشل الاختبار',

  'pill.generation_failed': 'فشل توليد',
  'pill.environment_error': 'خطأ بيئة',
  'pill.test_failed': 'فشل اختبار',

  'stage.queued': 'في الانتظار',
  'stage.checking_analysis': 'فحص التحليل',
  'stage.planning': 'التخطيط',
  'stage.generating': 'توليد الاختبارات',
  'stage.validating': 'التحقق',
  'stage.running_sandbox': 'التشغيل في البيئة المعزولة',
  'stage.accepting': 'التحقق النهائي',
  'stage.done': 'تم',

  'reason.unsupported_language': 'لغة غير مدعومة',
  'reason.invalid_after_repair': 'غير صالح حتى بعد محاولات الإصلاح',
  'reason.assertion_failed': 'فشلت التأكيدات',
  'reason.no_units': 'لا توجد دوال قابلة للاختبار',
  'reason.syntax_error': 'خطأ نحوي في الكود المصدر',

  'err.validation_error': 'الطلب غير صالح. تحقق من الإصدار والملفات والمستويات.',
  'err.unauthorized': 'انتهت جلستك. يرجى تسجيل الدخول من جديد.',
  'err.forbidden': 'ليست لديك صلاحية لهذا الإجراء.',
  'err.not_found': 'غير موجود.',
  'err.analysis_missing': 'تحليل هذا الإصدار لم ينتهِ بعد. انتظر قليلاً ثم أعد المحاولة.',
  'err.no_python_files': 'لا تحتوي الملفات المختارة على أي ملف Python.',
  'err.no_ready_tests': 'لا توجد اختبارات جاهزة للتنزيل بعد.',
  'err.coverage_not_ready': 'التغطية غير جاهزة بعد.',
  'err.conflict': 'هذا الإجراء غير ممكن في الحالة الحالية للمهمة.',
  'err.network': 'تعذّر الوصول إلى الخادم. تحقق من الاتصال وأعد المحاولة.',
  'err.unknown': 'حدث خطأ ما. يرجى المحاولة مرة أخرى.',
  'common.retry': 'إعادة المحاولة',
  'common.dismiss': 'إغلاق',
  'common.loading': 'جاري التحميل…',

  // modal flow (Dashboard -> Tests)
  'modal.close': 'إغلاق',
  'modal.back': 'رجوع',
  'picker.title': 'توليد الاختبارات',
  'picker.intro': 'اختر مشروعاً: ابدأ تشغيلاً جديداً للاختبارات أو راجع التشغيلات السابقة.',
  'picker.loading': 'جاري تحميل مشاريعك…',
  'picker.empty.title': 'ليس لديك أي مشروع بعد',
  'picker.empty.text': 'أنشئ مشروعاً وارفع الكود الخاص به أولاً، ثم يمكنك توليد الاختبارات له.',
  'picker.empty.cta': 'إنشاء مشروع',
  'picker.search': 'ابحث في المشاريع…',
  'picker.noMatch': 'لا يوجد مشروع مطابق لبحثك.',
  'picker.test': 'اختبار',
  'picker.tested': 'السابقة',
  'picker.showAll': 'عرض كل المشاريع',
  'newRun.title': 'تشغيل اختبارات جديد',
  'newRun.prior.title': 'سبق أن أُجريت اختبارات لهذا المشروع',
  'newRun.prior.last': 'آخر تشغيل: {when} · الإصدار {v} · {status}',
  'newRun.prior.view': 'عرض النتائج السابقة',
  'newRun.running.title': 'يوجد تشغيل ما زال جارياً',
  'newRun.running.open': 'فتحه',
  'confirm.title': 'هل تريد بدء تشغيل جديد؟',
  'confirm.text': 'لهذا المشروع {n} تشغيل سابق. التشغيل الجديد يبدأ من الصفر ويستهلك طلبات ذكاء اصطناعي، ولا يستبدل النتائج القديمة: تبقى ضمن «السابقة».',
  'confirm.yes': 'نعم، ابدأ تشغيلاً جديداً',
  'confirm.view': 'عرض النتائج السابقة',
  'confirm.back': 'رجوع',
  'history.title': 'الاختبارات السابقة',
  'history.subtitle': 'تشغيلات الاختبارات السابقة لهذا المشروع',
  'history.empty.title': 'لا توجد اختبارات بعد',
  'history.empty.text': 'لم يتم توليد أي اختبارات لهذا المشروع حتى الآن.',
  'history.empty.cta': 'ابدأ اختباراً',
  'history.new': 'تشغيل جديد',
  'history.version': 'الإصدار {v}',
  'history.tests': '{done} / {total} اختبار',
  'history.ready': '{n} جاهز',
  'history.localNote': 'هذه القائمة محفوظة في هذا المتصفح فقط. ستصبح كاملة على أي جهاز عندما يوفّر الخادم سجل التشغيلات.',
  'history.openById': 'فتح بمعرّف المهمة',
  'job.modalTitle': 'تشغيل الاختبارات',
  'job.fromHistory': 'العودة إلى «السابقة»',
};

const dict = { en, ar };

const humanize = (v: string): string => {
  const s = v.replace(/[_-]+/g, ' ').trim();
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : v;
};

export function useTestsT() {
  const { language } = useLanguage();
  const table = (language === 'ar' ? dict.ar : dict.en) as Record<string, string>;

  const t = useCallback(
    (key: Key, params?: Record<string, string | number>): string => {
      let text = table[key] ?? key;
      if (params) {
        for (const [k, v] of Object.entries(params)) text = text.split(`{${k}}`).join(String(v));
      }
      return text;
    },
    [table],
  );

  /** Translate a back-end value (status, stage, reason, error code); unknown values are humanized. */
  const label = useCallback(
    (prefix: 'status' | 'stage' | 'reason' | 'err' | 'level', value: string): string =>
      table[`${prefix}.${value}`] ?? humanize(value),
    [table],
  );

  /** Compact status text for narrow table cells (e.g. "Gen. failed"). */
  const short = useCallback(
    (status: string): string => table[`pill.${status}`] ?? table[`status.${status}`] ?? humanize(status),
    [table],
  );

  return { t, label, short, language, isRTL: language === 'ar' };
}