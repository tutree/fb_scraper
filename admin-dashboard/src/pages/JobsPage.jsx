import { useEffect, useState } from 'react'
import api from '../api'

const STATUS_COLORS = {
  completed: 'bg-emerald-100 text-emerald-800',
  running: 'bg-blue-100 text-blue-800',
  failed: 'bg-rose-100 text-rose-800',
  skipped: 'bg-amber-100 text-amber-800',
}

const getErrorMessage = (err, fallback) =>
  err?.response?.data?.detail ?? err?.message ?? fallback

export default function JobsPage() {
  const [status, setStatus] = useState(null)
  const [history, setHistory] = useState([])
  const [feedback, setFeedback] = useState(null)
  const [loading, setLoading] = useState(true)
  const [updating, setUpdating] = useState(false)

  const fetchAll = async () => {
    try {
      const [s, h] = await Promise.all([
        api.get('/automation/status'),
        api.get('/automation/history?limit=30'),
      ])
      setStatus(s.data)
      setHistory(Array.isArray(h.data) ? h.data : [])
    } catch (err) {
      setFeedback({ type: 'error', text: getErrorMessage(err, 'Failed to load job status') })
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchAll()
    const iv = setInterval(fetchAll, 10000)
    return () => clearInterval(iv)
  }, [])

  const update = async (patch) => {
    setUpdating(true)
    setFeedback(null)
    try {
      const res = await api.post('/automation/update', patch)
      setStatus(res.data)
      setFeedback({ type: 'success', text: 'Settings updated.' })
    } catch (err) {
      setFeedback({ type: 'error', text: getErrorMessage(err, 'Failed to update') })
    } finally {
      setUpdating(false)
    }
  }

  const triggerNow = async () => {
    setFeedback(null)
    try {
      await api.post('/automation/trigger')
      setFeedback({ type: 'success', text: 'Scrape triggered — running in background.' })
      setTimeout(fetchAll, 2000)
    } catch (err) {
      setFeedback({ type: 'error', text: getErrorMessage(err, 'Failed to trigger') })
    }
  }

  if (loading) {
    return <div className="flex min-h-[50vh] items-center justify-center text-slate-500">Loading jobs...</div>
  }

  const timeSince = (iso) => {
    if (!iso) return '—'
    const diff = (Date.now() - new Date(iso).getTime()) / 1000
    if (diff < 60) return `${Math.round(diff)}s ago`
    if (diff < 3600) return `${Math.round(diff / 60)}m ago`
    if (diff < 86400) return `${Math.round(diff / 3600)}h ago`
    return `${Math.round(diff / 86400)}d ago`
  }

  const duration = (start, end) => {
    if (!start || !end) return '—'
    const sec = (new Date(end) - new Date(start)) / 1000
    if (sec < 60) return `${Math.round(sec)}s`
    if (sec < 3600) return `${Math.floor(sec / 60)}m ${Math.round(sec % 60)}s`
    return `${Math.floor(sec / 3600)}h ${Math.floor((sec % 3600) / 60)}m`
  }

  return (
    <div className="mx-auto max-w-[1200px] space-y-6">
      {feedback && (
        <div className={`rounded-xl border px-4 py-3 text-sm ${feedback.type === 'error' ? 'border-rose-200 bg-rose-50 text-rose-700' : 'border-emerald-200 bg-emerald-50 text-emerald-700'}`}>
          {feedback.text}
        </div>
      )}

      {/* Live Status */}
      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-bold text-slate-900">Background Jobs</h2>
          <div className="flex items-center gap-2">
            <span className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-semibold ${status?.is_running ? 'bg-blue-100 text-blue-800' : status?.auto_scrape_enabled ? 'bg-emerald-100 text-emerald-800' : 'bg-slate-100 text-slate-600'}`}>
              <span className={`h-2 w-2 rounded-full ${status?.is_running ? 'bg-blue-500 animate-pulse' : status?.auto_scrape_enabled ? 'bg-emerald-500' : 'bg-slate-400'}`} />
              {status?.is_running ? 'Running' : status?.auto_scrape_enabled ? 'Scheduled' : 'Disabled'}
            </span>
          </div>
        </div>

        {status?.is_running && status?.current_step && (
          <div className="mt-3 rounded-lg border border-blue-200 bg-blue-50 px-4 py-3">
            <p className="text-sm font-medium text-blue-800">Currently: {status.current_step}</p>
          </div>
        )}

        <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Scheduler</p>
            <p className="mt-1 text-lg font-bold text-slate-900">{status?.scheduler_running ? 'Active' : 'Stopped'}</p>
          </div>
          <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Interval</p>
            <p className="mt-1 text-lg font-bold text-slate-900">{status?.interval_minutes} min</p>
          </div>
          <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Next Run</p>
            <p className="mt-1 text-sm font-bold text-slate-900">{status?.next_run ? new Date(status.next_run).toLocaleTimeString() : '—'}</p>
          </div>
          <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Last Run</p>
            <p className="mt-1 text-sm font-bold text-slate-900">{status?.last_run_at ? timeSince(status.last_run_at) : 'Never'}</p>
            {status?.last_run_status && <p className="mt-0.5 text-xs text-slate-500">{status.last_run_status}</p>}
          </div>
        </div>
      </section>

      {/* Configuration */}
      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <h3 className="text-sm font-bold text-slate-900">Configuration</h3>
        <div className="mt-4 flex flex-wrap items-center gap-6">
          <label className="flex items-center gap-2 text-sm text-slate-700">
            <input type="checkbox" checked={status?.auto_scrape_enabled || false} disabled={updating} onChange={(e) => update({ auto_scrape_enabled: e.target.checked })} className="h-4 w-4 rounded border-slate-300" />
            Auto-Scrape
          </label>
          <label className="flex items-center gap-2 text-sm text-slate-700">
            <input type="checkbox" checked={status?.auto_analyze || false} disabled={updating} onChange={(e) => update({ auto_analyze: e.target.checked })} className="h-4 w-4 rounded border-slate-300" />
            Auto-Analyze after scrape
          </label>
          <label className="flex items-center gap-2 text-sm text-slate-700">
            <input type="checkbox" checked={status?.auto_enrich || false} disabled={updating} onChange={(e) => update({ auto_enrich: e.target.checked })} className="h-4 w-4 rounded border-slate-300" />
            Auto-Enrich after analyze
          </label>
          <label className="flex items-center gap-2 text-sm text-slate-700">
            Interval:
            <select value={status?.interval_minutes || 30} disabled={updating} onChange={(e) => update({ interval_minutes: Number(e.target.value) })} className="rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm">
              <option value={5}>5 min</option>
              <option value={10}>10 min</option>
              <option value={15}>15 min</option>
              <option value={30}>30 min</option>
              <option value={60}>1 hour</option>
              <option value={120}>2 hours</option>
              <option value={360}>6 hours</option>
              <option value={720}>12 hours</option>
              <option value={1440}>24 hours</option>
            </select>
          </label>
          <button type="button" onClick={triggerNow} disabled={updating || status?.is_running} className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white disabled:bg-slate-400">
            {status?.is_running ? 'Running...' : 'Run Now'}
          </button>
        </div>
      </section>

      {/* Job History */}
      <section className="rounded-2xl border border-slate-200 bg-white shadow-sm">
        <div className="border-b border-slate-200 px-6 py-4">
          <h3 className="text-sm font-bold text-slate-900">Job History</h3>
        </div>
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-slate-200">
            <thead className="bg-slate-50 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-4 py-3">ID</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Started</th>
                <th className="px-4 py-3">Duration</th>
                <th className="px-4 py-3">Scraped</th>
                <th className="px-4 py-3">New</th>
                <th className="px-4 py-3">Analyzed</th>
                <th className="px-4 py-3">Enriched</th>
                <th className="px-4 py-3">Error</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {history.length === 0 ? (
                <tr><td colSpan={9} className="px-4 py-10 text-center text-sm text-slate-500">No job runs yet. Jobs run automatically on the configured interval.</td></tr>
              ) : (
                history.map((h) => (
                  <tr key={h.id} className="text-sm">
                    <td className="px-4 py-3 font-mono text-xs text-slate-500">{h.id}</td>
                    <td className="px-4 py-3">
                      <span className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-semibold ${STATUS_COLORS[h.status] || 'bg-slate-100 text-slate-600'}`}>{h.status}</span>
                    </td>
                    <td className="px-4 py-3 text-slate-600">{h.started_at ? new Date(h.started_at).toLocaleString() : '—'}</td>
                    <td className="px-4 py-3 text-slate-600">{duration(h.started_at, h.finished_at)}</td>
                    <td className="px-4 py-3 text-slate-900 font-medium">{h.scraped}</td>
                    <td className="px-4 py-3 text-slate-900 font-medium">{h.new_records}</td>
                    <td className="px-4 py-3 text-slate-900 font-medium">{h.analyzed}</td>
                    <td className="px-4 py-3 text-slate-900 font-medium">{h.enriched}</td>
                    <td className="max-w-[200px] truncate px-4 py-3 text-xs text-rose-600">{h.error || '—'}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  )
}
