import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { toast } from 'sonner'

import api from '../api'
import CookieExportGuide from '../components/CookieExportGuide'
import CookieUploadModal from '../components/CookieUploadModal'



const SCRAPER_STATUS_BADGES = {
  idle: 'bg-slate-100 text-slate-700',
  running: 'bg-emerald-100 text-emerald-800',
  stopping: 'bg-amber-100 text-amber-800',
  completed: 'bg-sky-100 text-sky-800',
  stopped: 'bg-rose-100 text-rose-800',
  failed: 'bg-rose-100 text-rose-800',
}

const getErrorMessage = (err, fallback) =>
  err?.response?.data?.detail ?? err?.message ?? fallback

const STEP_ORDER = [
  { id: 'init', label: 'Initializing' },
  { id: 'auth', label: 'Checking login' },
  { id: 'search', label: 'Searching keyword' },
  { id: 'extract', label: 'Extracting posts' },
  { id: 'profiles', label: 'Processing profiles' },
  { id: 'comments', label: 'Scraping comments' },
  { id: 'saving', label: 'Saving to database' },
  { id: 'done', label: 'Finished' },
]

const STEP_PATTERNS = [
  { id: 'init', regex: /STARTING SCRAPER SERVICE|Loading Facebook accounts|Creating browser page/i },
  { id: 'auth', regex: /Checking if already logged in|Not logged in, attempting login|Already logged in|Login successful/i },
  { id: 'search', regex: /KEYWORD \d+\/\d+|Navigating to search URL|Waiting .*for results to load/i },
  { id: 'extract', regex: /starting extraction|Preloading search feed|Total extracted:|Progressive scan round/i },
  { id: 'profiles', regex: /Processing \d+ links sequentially|Processing link \d+\/\d+|Personal profile detected|Not a personal profile/i },
  { id: 'comments', regex: /Extracting comments|Dialog opened, expanding all comments|Saved \d+ comments|No comments found/i },
  { id: 'saving', regex: /Saved to database|Saved as INVALID|Progress: \d+\/\d+ profiles saved/i },
  { id: 'done', regex: /SCRAPER SERVICE COMPLETED SUCCESSFULLY|finished with status=completed|finished with status=failed|finished with status=stopped/i },
]

const parseLogEntry = (raw) => {
  const m = String(raw || '').match(/^([^|]+)\|\s*([A-Z]+)\s*\|[^-]*-\s?(.*)$/)
  if (!m) {
    return {
      timestamp: null,
      level: 'INFO',
      message: String(raw || '').trim(),
      raw: String(raw || ''),
    }
  }
  return {
    timestamp: m[1].trim(),
    level: m[2].trim(),
    message: m[3].trim(),
    raw: String(raw || ''),
  }
}

const humanizeIssue = (message) => {
  const text = String(message || '')
  if (/Page Not Found|join or log into facebook|logged out/i.test(text)) {
    return 'Facebook session likely expired. Re-login is needed.'
  }
  if (/no active accounts|password missing|login failed/i.test(text)) {
    return 'Account credentials are incomplete or login failed.'
  }
  if (/No comments found/i.test(text)) {
    return 'Comment section opened but no parseable comments were found.'
  }
  if (/Comment button not found/i.test(text)) {
    return 'Could not find the comments button for this post card.'
  }
  if (/Stop requested/i.test(text)) {
    return 'Stop was requested by user.'
  }
  return text
}

const buildMonitor = (logs, task) => {
  const entries = (logs || []).map(parseLogEntry)
  const latest = entries.at(-1)

  let keywordsTotal = task?.requested_keywords?.length || 0
  let keywordsDone = 0
  let currentKeyword = ''
  let candidateProfiles = 0
  let queuedProfiles = 0
  let savedProfiles = 0
  let commentsFound = 0
  let errors = 0
  let warnings = 0
  let currentStepId = 'init'

  const activity = []
  const issues = []

  for (const entry of entries) {
    const msg = entry.message

    if (entry.level === 'ERROR') errors += 1
    if (entry.level === 'WARNING') warnings += 1

    const willSearch = msg.match(/Will search (\d+) keywords/i)
    if (willSearch) keywordsTotal = Number(willSearch[1])

    const keyProgress = msg.match(/KEYWORD (\d+)\/(\d+): '(.+)'/i)
    if (keyProgress) {
      keywordsDone = Math.max(keywordsDone, Number(keyProgress[1]) - 1)
      keywordsTotal = Math.max(keywordsTotal, Number(keyProgress[2]))
      currentKeyword = keyProgress[3]
    }

    const keywordDoneMatch = msg.match(/Keyword '.*' completed:/i)
    if (keywordDoneMatch) keywordsDone += 1

    const extractedMatch = msg.match(/Total extracted:\s+(\d+)\s+profile links/i)
    if (extractedMatch) candidateProfiles = Number(extractedMatch[1])

    const queueMatch = msg.match(/Processing (\d+) links sequentially/i)
    if (queueMatch) queuedProfiles = Number(queueMatch[1])

    const progressMatch = msg.match(/Progress:\s*(\d+)\/(\d+)\s*profiles saved/i)
    if (progressMatch) {
      savedProfiles = Number(progressMatch[1])
      queuedProfiles = Math.max(queuedProfiles, Number(progressMatch[2]))
    }

    const completeMatch = msg.match(/Completed:\s*(\d+)\s*users saved to database/i)
    if (completeMatch) savedProfiles = Number(completeMatch[1])

    const commentsMatch = msg.match(/(?:Scraped|Extracted|Saved)\s+(\d+)\s+comments/i)
    if (commentsMatch) commentsFound += Number(commentsMatch[1])

    for (const step of STEP_PATTERNS) {
      if (step.regex.test(msg)) currentStepId = step.id
    }

    if (
      /STARTING SCRAPER SERVICE|KEYWORD \d+\/\d+|Total extracted:|Processing link|Saved to database|Extracted \d+ comments|No comments found|completed|failed|stopped/i.test(msg)
    ) {
      activity.push(entry)
    }

    if (
      entry.level === 'ERROR' ||
      /No comments found|Comment button not found|Page Not Found|login failed|logged out/i.test(msg)
    ) {
      issues.push({
        level: entry.level === 'ERROR' ? 'error' : 'warning',
        text: humanizeIssue(msg),
        timestamp: entry.timestamp,
      })
    }
  }

  keywordsDone = Math.min(keywordsDone, keywordsTotal || keywordsDone)

  const stepIndex = STEP_ORDER.findIndex((s) => s.id === currentStepId)
  const terminalStatus = task?.status === 'completed' || task?.status === 'failed' || task?.status === 'stopped'
  const steps = STEP_ORDER.map((step, idx) => ({
    ...step,
    state: task?.status === 'failed' && idx === Math.max(stepIndex, 0)
      ? 'failed'
      : idx < stepIndex
        ? 'done'
        : idx === stepIndex && !terminalStatus
          ? 'active'
          : terminalStatus && step.id === 'done'
            ? (task?.status === 'failed' ? 'failed' : 'done')
            : 'pending',
  }))

  return {
    latest,
    steps,
    counters: {
      keywordsDone,
      keywordsTotal,
      currentKeyword,
      candidateProfiles,
      queuedProfiles,
      savedProfiles,
      commentsFound,
      warnings,
      errors,
    },
    activity: activity.slice(-15),
    issues: issues.slice(-8),
  }
}

export default function ScraperPage() {
  const [scraperTask, setScraperTask] = useState(null)
  const [scraperLogs, setScraperLogs] = useState([])
  const [cookieModalOpen, setCookieModalOpen] = useState(false)
  const [cookieStatus, setCookieStatus] = useState(null)
  const [cookieUrgencyMessage, setCookieUrgencyMessage] = useState('')
  const [logLines, setLogLines] = useState(300)
  const [showTechnicalLogs, setShowTechnicalLogs] = useState(false)
  const logsContainerRef = useRef(null)

  const [keywordModalOpen, setKeywordModalOpen] = useState(false)
  const [keywordInput, setKeywordInput] = useState('')
  const [savedKeywords, setSavedKeywords] = useState([])
  const [keywordSubmitting, setKeywordSubmitting] = useState(false)

  const fetchScraperStatus = useCallback(async () => {
    try {
      const res = await api.get(`/search/current`)
      setScraperTask(res.data || null)
    } catch {
      setScraperTask(null)
    }
  }, [])

  const fetchScraperLogs = useCallback(async (lines = logLines) => {
    try {
      const res = await api.get(`/search/logs`, { params: { lines } })
      setScraperLogs(Array.isArray(res.data?.lines) ? res.data.lines : [])
    } catch {
      setScraperLogs([])
    }
  }, [logLines])

  const fetchCookieStatus = useCallback(async () => {
    try {
      const res = await api.get(`/search/cookies/status`)
      setCookieStatus(res.data || null)
    } catch {
      setCookieStatus(null)
    }
  }, [])

  const fetchKeywords = useCallback(async () => {
    try {
      const res = await api.get(`/search/keywords`)
      setSavedKeywords(res.data?.keywords || [])
    } catch {
      setSavedKeywords([])
    }
  }, [])

  const submitKeywords = async () => {
    const newKws = keywordInput
      .split(/\r?\n|,|;/)
      .map((s) => s.trim())
      .filter(Boolean)
    if (newKws.length === 0) return
    setKeywordSubmitting(true)
    try {
      const res = await api.post(`/search/keywords`, { keywords: newKws })
      setSavedKeywords(res.data?.keywords || [])
      setKeywordInput('')
      toast.success(
        res.data?.added?.length
          ? `Added ${res.data.added.length} keyword(s). Total: ${res.data.total}`
          : 'All keywords already exist.',
      )
    } catch (err) {
      toast.error(getErrorMessage(err, 'Failed to add keywords'))
    } finally {
      setKeywordSubmitting(false)
    }
  }

  const removeKeyword = async (kw) => {
    try {
      const res = await api.delete(`/search/keywords`, { params: { keyword: kw } })
      setSavedKeywords(res.data?.keywords || [])
    } catch (err) {
      toast.error(getErrorMessage(err, 'Failed to remove keyword'))
    }
  }

  useEffect(() => {
    fetchScraperStatus()
    fetchScraperLogs(logLines)
    fetchCookieStatus()
    fetchKeywords()
  }, [fetchScraperStatus, fetchScraperLogs, fetchCookieStatus, fetchKeywords, logLines])

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const [healthRes, statusRes] = await Promise.all([
          api.get('/search/scraper-health'),
          api.get('/search/cookies/status'),
        ])
        if (cancelled) return
        const h = healthRes.data
        const statusOk = healthRes.status === 200 && statusRes.status === 200
        const hasWorkingCookie = statusRes.data?.has_valid_cookies === true
        const showCookieModal =
          statusOk &&
          !hasWorkingCookie &&
          h?.level === 'error' &&
          (h?.all_cookies_failed === true || h?.has_cookie_files === false)
        if (showCookieModal) {
          setCookieUrgencyMessage(
            h?.message || 'Upload a valid Facebook cookie to continue scraping.',
          )
          setCookieModalOpen(true)
        }
      } catch {
        /* ignore */
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    const status = scraperTask?.status
    if (!status || !['running', 'stopping'].includes(status)) return

    const intervalId = setInterval(() => {
      fetchScraperStatus()
      fetchScraperLogs(logLines)
    }, 1000)

    return () => clearInterval(intervalId)
  }, [scraperTask?.status, fetchScraperStatus, fetchScraperLogs, logLines])

  useEffect(() => {
    const logBox = logsContainerRef.current
    if (!logBox) return
    logBox.scrollTop = logBox.scrollHeight
  }, [scraperLogs])

  const scraperStatus = scraperTask?.status || 'idle'
  const scraperBadgeClass = SCRAPER_STATUS_BADGES[scraperStatus] || SCRAPER_STATUS_BADGES.idle
  const monitor = useMemo(() => buildMonitor(scraperLogs, scraperTask), [scraperLogs, scraperTask])

  return (
    <div className="min-h-screen bg-gradient-to-b from-slate-100 to-sky-50 px-4 py-8">
      <div className="mx-auto max-w-[1400px] space-y-6">
        <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="text-lg font-semibold text-slate-900">Task Status</h2>
              <p className="text-xs text-slate-600">Monitor the background scraper and manage cookies &amp; keywords.</p>
            </div>
            <span className={`rounded-full px-3 py-1 text-xs font-semibold capitalize ${scraperBadgeClass}`}>
              {scraperStatus}
            </span>
          </div>

          <div className="mt-4 space-y-3 rounded-xl border border-slate-200 p-3">
            <h3 className="text-sm font-semibold text-slate-800">Actions</h3>
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                onClick={() => {
                  setCookieUrgencyMessage('')
                  setCookieModalOpen(true)
                }}
                className="rounded-lg border border-sky-300 bg-sky-50 px-4 py-2 text-sm font-medium text-sky-700 hover:bg-sky-100"
              >
                Update Facebook Cookie
              </button>
              <button
                type="button"
                onClick={() => { setKeywordModalOpen(true); fetchKeywords() }}
                className="rounded-lg border border-violet-300 bg-violet-50 px-4 py-2 text-sm font-medium text-violet-700 hover:bg-violet-100"
              >
                Add Keywords
              </button>
              <button
                type="button"
                onClick={() => { fetchScraperStatus(); fetchScraperLogs(logLines) }}
                className="rounded-lg border border-slate-300 px-4 py-2 text-sm text-slate-700 hover:bg-slate-50"
              >
                Refresh
              </button>
            </div>
            <p className="text-xs text-slate-500">
              Task: {scraperTask?.task_id || 'none'} {scraperTask?.updated_at ? `| Updated ${new Date(scraperTask.updated_at).toLocaleString()}` : ''}
            </p>
            <div className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600">
              <p>
                Active account UIDs (credentials):{' '}
                {cookieStatus?.active_account_uids?.length ? cookieStatus.active_account_uids.join(', ') : 'none configured'}
              </p>
              <p>
                Cookie files on disk (UIDs):{' '}
                {cookieStatus?.saved_cookie_uids?.length
                  ? cookieStatus.saved_cookie_uids.join(', ')
                  : 'none'}
                {typeof cookieStatus?.sessions_with_cookies === 'number'
                  ? ` · ${cookieStatus.sessions_with_cookies} session file(s) with cookies`
                  : ''}
              </p>
              <p>
                Primary display UID: {cookieStatus?.latest_cookie_uid || 'none'}
                {cookieStatus?.updated_at ? ` | File updated ${new Date(cookieStatus.updated_at).toLocaleString()}` : ''}
              </p>
              <p>
                Cookie entries (primary file / total): {cookieStatus?.cookie_count ?? 0}
                {typeof cookieStatus?.total_cookie_entries === 'number'
                  ? ` / ${cookieStatus.total_cookie_entries} total across sessions`
                  : ''}
              </p>
            </div>
            {scraperTask?.requested_keywords && (
              <p className="text-xs text-slate-500">
                Requested keywords: {scraperTask.requested_keywords.join(', ')}
              </p>
            )}
            {scraperTask?.error && (
              <p className="rounded-md border border-rose-200 bg-rose-50 px-2 py-1 text-xs text-rose-700 truncate">
                Error: {scraperTask.error}
              </p>
            )}
            {scraperTask?.result?.error && !scraperTask?.error && (
              <p className="rounded-md border border-rose-200 bg-rose-50 px-2 py-1 text-xs text-rose-700 truncate">
                Error: {scraperTask.result.error}
              </p>
            )}
          </div>

          <div className="mt-4">
            <CookieExportGuide variant="full" />
          </div>

          <div className="mt-3 space-y-4 rounded-xl border border-slate-200 p-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h3 className="text-sm font-semibold text-slate-800">Run Monitor</h3>
              <p className="text-xs text-slate-500">
                {monitor.latest?.timestamp ? `Last event: ${monitor.latest.timestamp}` : 'Waiting for live updates'}
              </p>
            </div>

            <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
              <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs">
                <p className="text-slate-500">Keywords</p>
                <p className="mt-1 text-lg font-semibold text-slate-900">
                  {monitor.counters.keywordsDone}/{monitor.counters.keywordsTotal || 0}
                </p>
                <p className="mt-1 truncate text-slate-500">
                  {monitor.counters.currentKeyword || 'No active keyword'}
                </p>
              </div>
              <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs">
                <p className="text-slate-500">Candidate Profiles</p>
                <p className="mt-1 text-lg font-semibold text-slate-900">{monitor.counters.candidateProfiles}</p>
              </div>
              <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs">
                <p className="text-slate-500">Queued Profiles</p>
                <p className="mt-1 text-lg font-semibold text-slate-900">{monitor.counters.queuedProfiles}</p>
              </div>
              <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs">
                <p className="text-slate-500">Saved Profiles</p>
                <p className="mt-1 text-lg font-semibold text-slate-900">{monitor.counters.savedProfiles}</p>
              </div>
              <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs">
                <p className="text-slate-500">Comments Captured</p>
                <p className="mt-1 text-lg font-semibold text-slate-900">{monitor.counters.commentsFound}</p>
              </div>
            </div>

            <div className="grid gap-3 lg:grid-cols-2">
              <div className="rounded-lg border border-slate-200 p-3">
                <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-600">Pipeline</p>
                <div className="space-y-2">
                  {monitor.steps.map((step) => {
                    const stateClass = step.state === 'done'
                      ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
                      : step.state === 'active'
                        ? 'border-sky-200 bg-sky-50 text-sky-700'
                        : step.state === 'failed'
                          ? 'border-rose-200 bg-rose-50 text-rose-700'
                          : 'border-slate-200 bg-slate-50 text-slate-500'
                    return (
                      <div key={step.id} className={`rounded-md border px-2 py-1.5 text-xs ${stateClass}`}>
                        {step.label}
                      </div>
                    )
                  })}
                </div>
              </div>

              <div className="rounded-lg border border-slate-200 p-3">
                <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-600">Recent Activity</p>
                <div className="max-h-56 space-y-1 overflow-y-auto pr-1 text-xs">
                  {monitor.activity.length === 0 ? (
                    <p className="text-slate-500">No activity yet.</p>
                  ) : (
                    monitor.activity.map((entry, idx) => (
                      <div key={`${idx}-${entry.message.slice(0, 24)}`} className="rounded-md border border-slate-200 bg-slate-50 px-2 py-1.5">
                        <p className="text-slate-500">{entry.timestamp || 'now'}</p>
                        <p className="text-slate-700">{entry.message}</p>
                      </div>
                    ))
                  )}
                </div>
              </div>
            </div>

            <div className="rounded-lg border border-slate-200 p-3 overflow-hidden">
              <div className="mb-2 flex items-center justify-between">
                <p className="text-xs font-semibold uppercase tracking-wide text-slate-600">Issues</p>
                <p className="text-xs text-slate-500 whitespace-nowrap">Warnings: {monitor.counters.warnings} | Errors: {monitor.counters.errors}</p>
              </div>
              <div className="space-y-1 text-xs max-h-48 overflow-y-auto">
                {monitor.issues.length === 0 ? (
                  <p className="text-slate-500">No active issues detected.</p>
                ) : (
                  monitor.issues.map((issue, idx) => (
                    <p
                      key={`${idx}-${issue.text.slice(0, 24)}`}
                      className={`rounded px-2 py-1 truncate ${
                        issue.level === 'error'
                          ? 'bg-rose-50 text-rose-700'
                          : 'bg-amber-50 text-amber-700'
                      }`}
                      title={`${issue.timestamp ? issue.timestamp + ' - ' : ''}${issue.text}`}
                    >
                      {issue.timestamp ? `${issue.timestamp} - ` : ''}{issue.text}
                    </p>
                  ))
                )}
              </div>
            </div>

            <div className="rounded-lg border border-slate-200 p-3">
              <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                <div className="flex flex-wrap items-center gap-2">
                  <button
                    type="button"
                    onClick={() => setShowTechnicalLogs((prev) => !prev)}
                    className="rounded border border-slate-300 px-2 py-1 text-xs text-slate-700 hover:bg-slate-50"
                  >
                    {showTechnicalLogs ? 'Hide technical logs' : 'Show technical logs'}
                  </button>
                  <button
                    type="button"
                    onClick={() => setScraperLogs([])}
                    className="rounded border border-slate-300 px-2 py-1 text-xs text-slate-700 hover:bg-slate-50"
                  >
                    Clear logs
                  </button>
                </div>
                <div className="flex items-center gap-2 text-xs text-slate-600">
                  <span>Lines</span>
                  <select
                    value={logLines}
                    onChange={(e) => setLogLines(Number(e.target.value))}
                    className="rounded border border-slate-300 px-2 py-1"
                  >
                    <option value={80}>80</option>
                    <option value={120}>120</option>
                    <option value={200}>200</option>
                    <option value={300}>300</option>
                    <option value={500}>500</option>
                  </select>
                </div>
              </div>
              { (
                <div ref={logsContainerRef} className="h-80 overflow-y-auto rounded-lg bg-slate-950 p-2 font-mono text-[11px] text-slate-100">
                  {scraperLogs.length === 0 ? (
                    <p className="text-slate-400">No logs yet.</p>
                  ) : (
                    scraperLogs.map((line, idx) => <p key={`${idx}-${line.slice(0, 25)}`}>{line}</p>)
                  )}
                </div>
              )}
            </div>
          </div>
        </section>
      </div>

      <CookieUploadModal
        open={cookieModalOpen}
        onClose={() => setCookieModalOpen(false)}
        cookieStatus={cookieStatus}
        urgencyHint={cookieUrgencyMessage || undefined}
        onSuccess={async () => {
          setCookieUrgencyMessage('')
          await fetchCookieStatus()
        }}
      />

      {keywordModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/60 px-4">
          <div className="w-full max-w-lg rounded-2xl border border-slate-200 bg-white p-5 shadow-2xl">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h2 className="text-xl font-semibold text-slate-900">Manage Keywords</h2>
                <p className="mt-1 text-sm text-slate-600">
                  Add or remove keywords used by the background scraper.
                </p>
              </div>
              <button
                type="button"
                onClick={() => setKeywordModalOpen(false)}
                className="rounded-md border border-slate-300 px-3 py-2 text-sm text-slate-700 hover:bg-slate-50"
              >
                Close
              </button>
            </div>

            <div className="mt-4 space-y-3">
              <div className="flex flex-wrap gap-1.5 max-h-40 overflow-y-auto">
                {savedKeywords.length === 0 ? (
                  <p className="text-xs text-slate-500">No keywords configured yet.</p>
                ) : (
                  savedKeywords.map((kw) => (
                    <span
                      key={kw}
                      className="inline-flex items-center gap-1 rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs text-slate-700"
                    >
                      {kw}
                      <button
                        type="button"
                        onClick={() => removeKeyword(kw)}
                        className="ml-0.5 rounded-full text-slate-400 hover:text-rose-600 transition"
                        title={`Remove "${kw}"`}
                      >
                        &times;
                      </button>
                    </span>
                  ))
                )}
              </div>

              <textarea
                value={keywordInput}
                onChange={(e) => setKeywordInput(e.target.value)}
                rows={4}
                placeholder="Enter new keywords (one per line, or comma/semicolon separated)&#10;math tutor&#10;looking for tutor"
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              />
            </div>

            <div className="mt-4 flex items-center justify-between gap-3">
              <p className="text-xs text-slate-500">{savedKeywords.length} keyword(s) saved</p>
              <button
                type="button"
                onClick={submitKeywords}
                disabled={!keywordInput.trim() || keywordSubmitting}
                className="rounded-lg bg-violet-600 px-4 py-2 text-sm font-medium text-white hover:bg-violet-700 disabled:bg-slate-400 transition"
              >
                {keywordSubmitting ? 'Adding...' : 'Add Keywords'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
