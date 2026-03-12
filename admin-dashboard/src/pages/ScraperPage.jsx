import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import axios from 'axios'

const API_BASE = '/api/v1'

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
  const [scraperStarting, setScraperStarting] = useState(false)
  const [scraperStopping, setScraperStopping] = useState(false)
  const [cookieModalOpen, setCookieModalOpen] = useState(false)
  const [cookieJsonInput, setCookieJsonInput] = useState('')
  const [cookieSubmitting, setCookieSubmitting] = useState(false)
  const [cookieStatus, setCookieStatus] = useState(null)
  const [feedback, setFeedback] = useState(null)
  const [scraperConfig, setScraperConfig] = useState({
    keywords: '',
    maxResults: 10,
    useDefaultKeywords: false,
  })
  const [logLines, setLogLines] = useState(120)
  const [showTechnicalLogs, setShowTechnicalLogs] = useState(false)
  const logsContainerRef = useRef(null)

  const parseKeywords = (raw) => {
    const parts = String(raw || '')
      .split(/\r?\n|,|;/)
      .map((item) => item.trim())
      .filter(Boolean)
    return [...new Set(parts)]
  }

  const fetchScraperStatus = useCallback(async () => {
    try {
      const res = await axios.get(`${API_BASE}/search/current`)
      setScraperTask(res.data || null)
    } catch {
      setScraperTask(null)
    }
  }, [])

  const fetchScraperLogs = useCallback(async (lines = logLines) => {
    try {
      const res = await axios.get(`${API_BASE}/search/logs`, { params: { lines } })
      setScraperLogs(Array.isArray(res.data?.lines) ? res.data.lines : [])
    } catch {
      setScraperLogs([])
    }
  }, [logLines])

  const fetchCookieStatus = useCallback(async () => {
    try {
      const res = await axios.get(`${API_BASE}/search/cookies/status`)
      setCookieStatus(res.data || null)
    } catch {
      setCookieStatus(null)
    }
  }, [])

  const startScraper = async () => {
    setScraperStarting(true)
    setFeedback(null)
    try {
      const keywords = parseKeywords(scraperConfig.keywords)
      if (!scraperConfig.useDefaultKeywords && keywords.length === 0) {
        setFeedback({
          type: 'error',
          text: 'Enter at least one keyword or enable "Use default keywords".',
        })
        return
      }

      await axios.post(`${API_BASE}/search/start`, {
        keywords: scraperConfig.useDefaultKeywords ? null : keywords,
        max_results: Math.max(1, Number(scraperConfig.maxResults) || 100),
        use_proxy: true,
      })

      setFeedback({
        type: 'success',
        text: scraperConfig.useDefaultKeywords
          ? 'Scraper started with default keywords from config/keywords.json.'
          : `Scraper started with ${keywords.length} custom keyword(s).`,
      })
      await Promise.all([fetchScraperStatus(), fetchScraperLogs(logLines)])
    } catch (err) {
      setFeedback({ type: 'error', text: getErrorMessage(err, 'Failed to start scraper') })
    } finally {
      setScraperStarting(false)
    }
  }

  const stopScraper = async () => {
    setScraperStopping(true)
    setFeedback(null)
    try {
      const res = await axios.post(`${API_BASE}/search/stop`)
      setFeedback({
        type: 'success',
        text: res.data?.message || 'Stop requested. Waiting for scraper to halt.',
      })
      await Promise.all([fetchScraperStatus(), fetchScraperLogs(logLines)])
    } catch (err) {
      setFeedback({ type: 'error', text: getErrorMessage(err, 'Failed to stop scraper') })
    } finally {
      setScraperStopping(false)
    }
  }

  const submitCookieUpdate = async () => {
    setCookieSubmitting(true)
    setFeedback(null)
    try {
      const res = await axios.post(`${API_BASE}/search/cookies`, {
        cookie_json: cookieJsonInput,
      })
      setFeedback({
        type: 'success',
        text: `${res.data?.message || 'Cookie updated successfully.'} (${res.data?.cookie_count || 0} cookies saved)`,
      })
      setCookieJsonInput('')
      setCookieModalOpen(false)
      await fetchCookieStatus()
    } catch (err) {
      setFeedback({ type: 'error', text: getErrorMessage(err, 'Failed to update cookie') })
    } finally {
      setCookieSubmitting(false)
    }
  }

  useEffect(() => {
    fetchScraperStatus()
    fetchScraperLogs(logLines)
    fetchCookieStatus()
  }, [fetchScraperStatus, fetchScraperLogs, fetchCookieStatus, logLines])

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
  const scraperIsActive = ['running', 'stopping'].includes(scraperStatus)
  const scraperBadgeClass = SCRAPER_STATUS_BADGES[scraperStatus] || SCRAPER_STATUS_BADGES.idle
  const canStartScraper = !scraperIsActive && !scraperStarting
  const canStopScraper = scraperIsActive && scraperStatus !== 'stopped' && !scraperStopping
  const monitor = useMemo(() => buildMonitor(scraperLogs, scraperTask), [scraperLogs, scraperTask])

  return (
    <div className="min-h-screen bg-gradient-to-b from-slate-100 to-sky-50 px-4 py-8">
      <div className="mx-auto max-w-[1400px] space-y-6">
        <header className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
          <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
            <div>
              <h1 className="text-3xl font-bold text-slate-900">Scraper Control</h1>
              <p className="text-sm text-slate-600">Run management with live progress, activity, and issue tracking.</p>
            </div>
            <nav className="flex gap-2">
              <Link to="/" className="rounded-md border border-slate-300 px-3 py-2 text-sm text-slate-700 hover:bg-slate-50">Leads</Link>
              <Link to="/comments" className="rounded-md border border-slate-300 px-3 py-2 text-sm text-slate-700 hover:bg-slate-50">Comments</Link>
              <Link to="/scraper" className="rounded-md bg-slate-900 px-3 py-2 text-sm font-medium text-white">Scraper</Link>
            </nav>
          </div>
        </header>

        {feedback && (
          <div className={`rounded-xl border px-4 py-3 text-sm ${feedback.type === 'error' ? 'border-rose-200 bg-rose-50 text-rose-700' : 'border-emerald-200 bg-emerald-50 text-emerald-700'}`}>
            {feedback.text}
          </div>
        )}

        <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="text-lg font-semibold text-slate-900">Task Status</h2>
              <p className="text-xs text-slate-600">Start and stop scraper jobs from this page.</p>
            </div>
            <span className={`rounded-full px-3 py-1 text-xs font-semibold capitalize ${scraperBadgeClass}`}>
              {scraperStatus}
            </span>
          </div>

          <div className="mt-4 grid gap-3 lg:grid-cols-2">
            <div className="space-y-3 rounded-xl border border-slate-200 p-3">
              <h3 className="text-sm font-semibold text-slate-800">Actions</h3>
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={startScraper}
                  disabled={!canStartScraper}
                  className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white disabled:bg-slate-400"
                >
                  {scraperStarting ? 'Starting...' : 'Start Scraper'}
                </button>
                <button
                  type="button"
                  onClick={stopScraper}
                  disabled={!canStopScraper}
                  className="rounded-lg border border-rose-300 bg-rose-50 px-4 py-2 text-sm font-medium text-rose-700 disabled:opacity-40"
                >
                  {scraperStopping ? 'Stopping...' : 'Stop Scraper'}
                </button>
                <button
                  type="button"
                  onClick={() => { fetchScraperStatus(); fetchScraperLogs(logLines) }}
                  className="rounded-lg border border-slate-300 px-4 py-2 text-sm text-slate-700 hover:bg-slate-50"
                >
                  Refresh
                </button>
                <button
                  type="button"
                  onClick={() => setCookieModalOpen(true)}
                  className="rounded-lg border border-sky-300 bg-sky-50 px-4 py-2 text-sm font-medium text-sky-700 hover:bg-sky-100"
                >
                  Update Facebook Cookie
                </button>
              </div>
              <p className="text-xs text-slate-500">
                Task: {scraperTask?.task_id || 'none'} {scraperTask?.updated_at ? `| Updated ${new Date(scraperTask.updated_at).toLocaleString()}` : ''}
              </p>
              <div className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600">
                <p>
                  Active account UIDs: {cookieStatus?.active_account_uids?.length ? cookieStatus.active_account_uids.join(', ') : 'none configured'}
                </p>
                <p>
                  Latest saved cookie UID: {cookieStatus?.latest_cookie_uid || 'none'}
                  {cookieStatus?.updated_at ? ` | Updated ${new Date(cookieStatus.updated_at).toLocaleString()}` : ''}
                </p>
                <p>
                  Saved cookie count: {cookieStatus?.cookie_count ?? 0}
                </p>
              </div>
              {scraperTask?.requested_keywords && (
                <p className="text-xs text-slate-500">
                  Requested keywords: {scraperTask.requested_keywords.join(', ')}
                </p>
              )}
              {scraperTask?.requested_max_results != null && (
                <p className="text-xs text-slate-500">
                  Requested max results: {scraperTask.requested_max_results}
                </p>
              )}
              {scraperTask?.error && (
                <p className="rounded-md border border-rose-200 bg-rose-50 px-2 py-1 text-xs text-rose-700">
                  Error: {scraperTask.error}
                </p>
              )}
              {scraperTask?.result?.error && !scraperTask?.error && (
                <p className="rounded-md border border-rose-200 bg-rose-50 px-2 py-1 text-xs text-rose-700">
                  Error: {scraperTask.result.error}
                </p>
              )}
            </div>

            <div className="space-y-3 rounded-xl border border-slate-200 p-3">
              <h3 className="text-sm font-semibold text-slate-800">Config</h3>
              <label className="flex items-center gap-2 text-xs text-slate-700">
                <input
                  type="checkbox"
                  checked={scraperConfig.useDefaultKeywords}
                  onChange={(e) => setScraperConfig((prev) => ({ ...prev, useDefaultKeywords: e.target.checked }))}
                  className="h-4 w-4 rounded border-slate-300"
                />
                Use default keywords from backend config (config/keywords.json)
              </label>
              <label className="block text-xs text-slate-600">
                Custom keywords (newline/comma/semicolon separated)
                <textarea
                  value={scraperConfig.keywords}
                  onChange={(e) => setScraperConfig((prev) => ({ ...prev, keywords: e.target.value }))}
                  rows={5}
                  placeholder="math tutor&#10;looking for tutor"
                  disabled={scraperConfig.useDefaultKeywords}
                  className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                />
              </label>
              {!scraperConfig.useDefaultKeywords && (
                <p className="text-xs text-slate-500">
                  Parsed keywords: {parseKeywords(scraperConfig.keywords).length}
                </p>
              )}
              <label className="block text-xs text-slate-600">
                Max results
                <input
                  type="number"
                  min={1}
                  value={scraperConfig.maxResults}
                  onChange={(e) => setScraperConfig((prev) => ({ ...prev, maxResults: e.target.value }))}
                  className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                />
              </label>
            </div>

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

            <div className="rounded-lg border border-slate-200 p-3">
              <div className="mb-2 flex items-center justify-between">
                <p className="text-xs font-semibold uppercase tracking-wide text-slate-600">Issues</p>
                <p className="text-xs text-slate-500">Warnings: {monitor.counters.warnings} | Errors: {monitor.counters.errors}</p>
              </div>
              <div className="space-y-1 text-xs">
                {monitor.issues.length === 0 ? (
                  <p className="text-slate-500">No active issues detected.</p>
                ) : (
                  monitor.issues.map((issue, idx) => (
                    <p
                      key={`${idx}-${issue.text.slice(0, 24)}`}
                      className={`rounded px-2 py-1 ${
                        issue.level === 'error'
                          ? 'bg-rose-50 text-rose-700'
                          : 'bg-amber-50 text-amber-700'
                      }`}
                    >
                      {issue.timestamp ? `${issue.timestamp} - ` : ''}{issue.text}
                    </p>
                  ))
                )}
              </div>
            </div>

            <div className="rounded-lg border border-slate-200 p-3">
              <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                <button
                  type="button"
                  onClick={() => setShowTechnicalLogs((prev) => !prev)}
                  className="rounded border border-slate-300 px-2 py-1 text-xs text-slate-700 hover:bg-slate-50"
                >
                  {showTechnicalLogs ? 'Hide technical logs' : 'Show technical logs'}
                </button>
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
                    <option value={400}>400</option>
                  </select>
                </div>
              </div>
              {showTechnicalLogs && (
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

      {cookieModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/60 px-4">
          <div className="w-full max-w-3xl rounded-2xl border border-slate-200 bg-white p-5 shadow-2xl">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h2 className="text-xl font-semibold text-slate-900">Update Facebook Cookie</h2>
                <p className="mt-1 text-sm text-slate-600">
                  Paste the exported Facebook cookie JSON. The backend will validate it, detect the account from <span className="font-mono">c_user</span>, and update the stored session file.
                </p>
              </div>
              <button
                type="button"
                onClick={() => setCookieModalOpen(false)}
                className="rounded-md border border-slate-300 px-3 py-2 text-sm text-slate-700 hover:bg-slate-50"
              >
                Close
              </button>
            </div>

            <div className="mt-4 space-y-3">
              <div className="rounded-lg border border-sky-200 bg-sky-50 px-3 py-2 text-xs text-sky-800">
                Accepted formats: raw cookie array from the browser extension, or Playwright <span className="font-mono">storage_state</span> JSON.
              </div>
              <textarea
                value={cookieJsonInput}
                onChange={(e) => setCookieJsonInput(e.target.value)}
                rows={16}
                placeholder='[{"domain":".facebook.com","name":"c_user","value":"100..."}]'
                className="w-full rounded-xl border border-slate-300 px-3 py-3 font-mono text-sm text-slate-800"
              />
            </div>

            <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
              <p className="text-xs text-slate-500">
                Current latest UID: {cookieStatus?.latest_cookie_uid || 'none'}
              </p>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => setCookieModalOpen(false)}
                  className="rounded-lg border border-slate-300 px-4 py-2 text-sm text-slate-700 hover:bg-slate-50"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={submitCookieUpdate}
                  disabled={!cookieJsonInput.trim() || cookieSubmitting}
                  className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white disabled:bg-slate-400"
                >
                  {cookieSubmitting ? 'Saving...' : 'Save Cookie'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
