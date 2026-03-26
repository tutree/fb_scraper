import { useEffect, useMemo, useRef, useState } from 'react'
import { toast } from 'sonner'

import api from './api'
import { useAuth } from './contexts/AuthContext'
import LeadDetailModal from './components/LeadDetailModal'



const USER_TYPE_BADGES = {
  customer: 'bg-sky-100 text-sky-800',
  tutor: 'bg-emerald-100 text-emerald-800',
  unknown: 'bg-slate-100 text-slate-700',
}

const STATUS_BADGES = {
  pending: 'bg-amber-100 text-amber-800',
  contacted: 'bg-emerald-100 text-emerald-800',
  not_interested: 'bg-rose-100 text-rose-800',
  invalid: 'bg-slate-100 text-slate-700',
}

const getErrorMessage = (err, fallback) =>
  err?.response?.data?.detail ?? err?.message ?? fallback

function getPostAgeHours(ts) {
  if (!ts) return null
  const diff = Date.now() - new Date(ts).getTime()
  return diff / (1000 * 60 * 60)
}

function getPostAgeRowClass(ts) {
  const hours = getPostAgeHours(ts)
  if (hours === null) return ''
  if (hours < 5) return 'bg-emerald-50'
  if (hours < 24) return 'bg-sky-50'
  if (hours < 72) return 'bg-amber-50'
  return ''
}

function formatRelativeTime(ts) {
  if (!ts) return '—'
  const hours = getPostAgeHours(ts)
  if (hours === null) return '—'
  if (hours < 1) return `${Math.round(hours * 60)}m ago`
  if (hours < 24) return `${Math.round(hours)}h ago`
  const days = Math.round(hours / 24)
  if (days === 1) return '1 day ago'
  if (days < 7) return `${days} days ago`
  const weeks = Math.round(days / 7)
  if (weeks === 1) return '1 week ago'
  if (weeks < 5) return `${weeks} weeks ago`
  return new Date(ts).toLocaleDateString()
}

function App() {
  const { isAdmin } = useAuth()
  const [results, setResults] = useState([])
  const [stats, setStats] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [jobStatus, setJobStatus] = useState(null)
  const [selectedResult, setSelectedResult] = useState(null)
  const [showDetailDialog, setShowDetailDialog] = useState(false)
  const [filters, setFilters] = useState({
    userType: 'customer',
    status: '',
    analyzed: '',
    sortBy: 'post_date_timestamp',
    sortOrder: 'desc',
    keyword: '',
    q: '',
  })
  const [currentPage, setCurrentPage] = useState(1)
  const [itemsPerPage, setItemsPerPage] = useState(20)
  const [totalItems, setTotalItems] = useState(0)
  const [selectedIds, setSelectedIds] = useState(new Set())
  const [analyzingBatch, setAnalyzingBatch] = useState(false)
  const [enrichingBatch, setEnrichingBatch] = useState(false)
  const [deleteConfirm, setDeleteConfirm] = useState({ isOpen: false, ids: [], type: '', isDeleting: false })
  const [exporting, setExporting] = useState(false)
  const [scraperHealth, setScraperHealth] = useState(null)
  const selectAllRef = useRef(null)


  const fetchData = async () => {
    try {
      setLoading(true)
      const params = new URLSearchParams()
      if (filters.userType) params.append('user_type', filters.userType)
      if (filters.status) params.append('status', filters.status)
      if (filters.analyzed) params.append('analyzed', filters.analyzed)
      if (filters.sortBy) params.append('sort_by', filters.sortBy)
      if (filters.sortOrder) params.append('sort_order', filters.sortOrder)
      if (filters.keyword) params.append('keyword', filters.keyword)
      if (filters.q) params.append('q', filters.q)
      params.append('skip', (currentPage - 1) * itemsPerPage)
      params.append('limit', itemsPerPage)

      const [resultsRes, statsRes] = await Promise.all([
        api.get(`/results/?${params}`),
        api.get(`/dashboard/stats`),
      ])

      const items = Array.isArray(resultsRes.data?.items) ? resultsRes.data.items : []
      const idsOnPage = new Set(items.map((item) => item.id))
      setResults(items)
      setTotalItems(resultsRes.data?.total ?? 0)
      setStats(statsRes.data)
      setSelectedIds((prev) => new Set([...prev].filter((id) => idsOnPage.has(id))))
      setError(null)
    } catch (err) {
      setError(getErrorMessage(err, 'Failed to load dashboard data'))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchData()
  }, [filters, currentPage, itemsPerPage])

  useEffect(() => {
    const fetchJobStatus = async () => {
      try {
        const res = await api.get('/automation/status')
        setJobStatus(res.data)
      } catch { /* silent */ }
    }
    fetchJobStatus()
    const interval = setInterval(fetchJobStatus, 15000)
    return () => clearInterval(interval)
  }, [])

  useEffect(() => {
    if (!jobStatus?.is_running) return
    const interval = setInterval(fetchData, 10000)
    return () => clearInterval(interval)
  }, [jobStatus?.is_running, filters, currentPage, itemsPerPage])

  useEffect(() => {
    const fetchHealth = async () => {
      try {
        const res = await api.get('/search/scraper-health')
        setScraperHealth(res.data)
      } catch { /* silent */ }
    }
    fetchHealth()
    const interval = setInterval(fetchHealth, 30000)
    return () => clearInterval(interval)
  }, [])

  useEffect(() => {
    const isOpen = deleteConfirm.isOpen
    document.body.style.overflow = isOpen ? 'hidden' : ''
    return () => { document.body.style.overflow = '' }
  }, [deleteConfirm.isOpen])

  const updateStatus = async (id, newStatus) => {
    try {
      await api.patch(`/results/${id}`, { status: newStatus })
      await fetchData()
    } catch (err) {
      toast.error(getErrorMessage(err, 'Failed to update status'))
    }
  }

  const enrichSelected = async () => {
    const ids = [...selectedIds]
    if (ids.length === 0) return

    const eligible = []
    const skippedNames = []
    for (const id of ids) {
      const row = results.find((r) => r.id === id)
      if (row && (!row.name || !row.location)) {
        skippedNames.push(row.name || 'Unknown')
      } else {
        eligible.push(id)
      }
    }

    if (eligible.length === 0) {
      toast.error(`All ${ids.length} selected leads skipped — name + location required. Missing for: ${skippedNames.join(', ')}`)
      return
    }

    setEnrichingBatch(true)
    try {
      const res = await api.post(`/results/enrich/batch`, {
        result_ids: eligible,
        force_re_enrich: true,
      })
      const { succeeded = 0, skipped = 0, failed = 0 } = res.data || {}
      const parts = [`${succeeded} enriched`]
      if (skipped > 0) parts.push(`${skipped} skipped`)
      if (failed > 0) parts.push(`${failed} failed`)
      if (skippedNames.length > 0) parts.push(`${skippedNames.length} skipped (no location): ${skippedNames.join(', ')}`)
      const bad = (failed > 0 || skippedNames.length > 0) && succeeded === 0
      ;(bad ? toast.error : toast.success)(`Enrichment: ${parts.join(' · ')}`)
      setSelectedIds(new Set())
      await fetchData()
    } catch (err) {
      toast.error(getErrorMessage(err, 'Failed to run batch enrichment'))
    } finally {
      setEnrichingBatch(false)
    }
  }

  const deleteSelected = async () => {
    const ids = [...selectedIds]
    if (ids.length === 0) return
    setDeleteConfirm({ isOpen: true, ids, type: 'bulk', isDeleting: false })
  }

  const deleteSingle = async (id, e) => {
    e.stopPropagation()
    setDeleteConfirm({ isOpen: true, ids: [id], type: 'single', isDeleting: false })
  }

  const executeDelete = async () => {
    setDeleteConfirm(prev => ({ ...prev, isDeleting: true }))
    try {
      if (deleteConfirm.type === 'bulk') {
        const res = await api.post(`/results/bulk-delete`, { ids: deleteConfirm.ids })
        toast.success(res.data?.message || 'Deleted successfully')
        setSelectedIds(new Set())
      } else {
        const id = deleteConfirm.ids[0];
        const res = await api.delete(`/results/${id}`)
        toast.success(res.data?.message || 'Deleted successfully')
        setSelectedIds((prev) => {
          const next = new Set(prev)
          next.delete(id)
          return next
        })
      }
      
      // OPTIMISTIC UPDATE: Refresh UI instantly
      setResults(prev => prev.filter(r => !deleteConfirm.ids.includes(r.id)))

      await fetchData()
    } catch (err) {
      toast.error(getErrorMessage(err, 'Failed to delete'))
    } finally {
      setDeleteConfirm({ isOpen: false, ids: [], type: '', isDeleting: false })
    }
  }

  const analyzeSelected = async () => {
    const ids = [...selectedIds]
    if (ids.length === 0) return
    setAnalyzingBatch(true)
    try {
      const res = await api.post(`/results/analyze/batch`, {
        result_ids: ids,
        force_reanalyze: true,
      })
      const { succeeded = 0, skipped = 0, failed = 0 } = res.data || {}
      const msg = `Analysis batch: ${succeeded} analyzed, ${skipped} skipped, ${failed} failed.`
      if (failed > 0) toast.warning(msg)
      else toast.success(msg)
      setSelectedIds(new Set())
      await fetchData()
    } catch (err) {
      toast.error(getErrorMessage(err, 'Failed to run batch analysis'))
    } finally {
      setAnalyzingBatch(false)
    }
  }

  const openDetail = (result) => {
    setSelectedResult(result)
    setShowDetailDialog(true)
  }

  const closeDetail = () => {
    setShowDetailDialog(false)
    setSelectedResult(null)
  }

  const exportEnriched = async () => {
    setExporting(true)
    try {
      const res = await api.get('/results/export/enriched', { responseType: 'blob' })
      const disposition = res.headers['content-disposition'] || ''
      const match = disposition.match(/filename="?(.+?)"?$/)
      const filename = match ? match[1] : 'enriched_leads.xlsx'
      const url = window.URL.createObjectURL(res.data)
      const a = document.createElement('a')
      a.href = url
      a.download = filename
      document.body.appendChild(a)
      a.click()
      a.remove()
      window.URL.revokeObjectURL(url)
      toast.success('Enriched leads exported successfully.')
    } catch (err) {
      toast.error(getErrorMessage(err, 'Failed to export enriched leads'))
    } finally {
      setExporting(false)
    }
  }

  const pageIds = useMemo(() => results.map((result) => result.id), [results])
  const allSelected = pageIds.length > 0 && pageIds.every((id) => selectedIds.has(id))
  const someSelected = pageIds.some((id) => selectedIds.has(id))
  useEffect(() => {
    if (selectAllRef.current) {
      selectAllRef.current.indeterminate = !allSelected && someSelected
    }
  }, [allSelected, someSelected])

  const toggleSelectAll = () => {
    if (allSelected) {
      setSelectedIds((prev) => new Set([...prev].filter((id) => !pageIds.includes(id))))
      return
    }
    setSelectedIds((prev) => new Set([...prev, ...pageIds]))
  }

  const toggleRow = (id) => {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const totalPages = Math.max(1, Math.ceil(totalItems / itemsPerPage))

  const getPageNumbers = () => {
    if (totalPages <= 5) return Array.from({ length: totalPages }, (_, i) => i + 1)
    if (currentPage <= 3) return [1, 2, 3, 4, '...', totalPages]
    if (currentPage >= totalPages - 2) return [1, '...', totalPages - 3, totalPages - 2, totalPages - 1, totalPages]
    return [1, '...', currentPage - 1, currentPage, currentPage + 1, '...', totalPages]
  }

  if (loading && !stats) {
    return <div className="flex min-h-screen items-center justify-center bg-slate-100 text-slate-600">Loading...</div>
  }

  if (error) {
    return <div className="mx-auto mt-8 max-w-4xl rounded-xl border border-rose-200 bg-rose-50 p-4 text-rose-700">Error: {error}</div>
  }

  return (
    <div className="min-h-screen bg-gradient-to-b from-slate-100 to-sky-50">
      <div className="mx-auto max-w-[1400px] space-y-6">
        {scraperHealth && scraperHealth.level !== 'ok' && (
          <div className={`flex items-center gap-3 rounded-xl border px-4 py-3 text-sm font-medium ${
            scraperHealth.level === 'error'
              ? 'border-rose-300 bg-rose-50 text-rose-800'
              : 'border-amber-300 bg-amber-50 text-amber-800'
          }`}>
            <span className="text-lg">{scraperHealth.level === 'error' ? '\u26A0' : '\u26A0'}</span>
            <span>{scraperHealth.message}</span>
            {scraperHealth.last_cookie_ok_at && (
              <span className="ml-auto text-xs font-normal opacity-70">
                Last valid session: {formatRelativeTime(scraperHealth.last_cookie_ok_at)}
              </span>
            )}
          </div>
        )}

        {jobStatus && (() => {
          const { is_running, last_run_status, last_run_at, current_step, auto_scrape_enabled, next_run } = jobStatus
          let bg, border, text, dot, label, detail

          if (is_running) {
            bg = 'bg-blue-50'; border = 'border-blue-200'; text = 'text-blue-800'; dot = 'bg-blue-500'
            label = 'Scraper Running'
            detail = current_step || 'Working...'
          } else if (last_run_status === 'completed') {
            bg = 'bg-emerald-50'; border = 'border-emerald-200'; text = 'text-emerald-800'; dot = 'bg-emerald-500'
            label = 'Last Run Succeeded'
            detail = last_run_at ? `Completed ${formatRelativeTime(last_run_at)}` : 'Completed'
          } else if (last_run_status === 'failed') {
            bg = 'bg-rose-50'; border = 'border-rose-200'; text = 'text-rose-800'; dot = 'bg-rose-500'
            label = 'Last Run Failed'
            detail = last_run_at ? `Failed ${formatRelativeTime(last_run_at)}` : 'Failed'
          } else if (last_run_status === 'skipped') {
            bg = 'bg-amber-50'; border = 'border-amber-200'; text = 'text-amber-800'; dot = 'bg-amber-500'
            label = 'Last Run Skipped'
            detail = last_run_at ? formatRelativeTime(last_run_at) : ''
          } else {
            bg = 'bg-slate-50'; border = 'border-slate-200'; text = 'text-slate-600'; dot = 'bg-slate-400'
            label = auto_scrape_enabled ? 'Scraper Idle' : 'Scraper Disabled'
            detail = next_run ? `Next run ${formatRelativeTime(next_run)}` : ''
          }

          return (
            <div className={`flex items-center justify-between rounded-xl border ${border} ${bg} px-4 py-3`}>
              <div className={`flex items-center gap-3 text-sm font-medium ${text}`}>
                <span className="relative flex h-2.5 w-2.5">
                  {is_running && <span className={`absolute inline-flex h-full w-full animate-ping rounded-full ${dot} opacity-75`} />}
                  <span className={`relative inline-flex h-2.5 w-2.5 rounded-full ${dot}`} />
                </span>
                {label}
                {detail && <span className="font-normal opacity-75">&mdash; {detail}</span>}
              </div>
              {!is_running && auto_scrape_enabled && next_run && (
                <span className={`text-xs ${text} opacity-60`}>Next: {new Date(next_run).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
              )}
            </div>
          )
        })()}

        {stats && (
          <section className="grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-6">
            {[
              ['Total Leads', stats.total],
              ['Customers', stats.customers],
              ['Tutors', stats.tutors],
              ['Not Analyzed', stats.not_analyzed || 0],
              ['Pending', stats.pending],
              ['Contacted', stats.contacted],
            ].map(([label, value]) => (
              <div key={label} className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
                <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</p>
                <p className="mt-1 text-3xl font-bold text-slate-900">{value}</p>
              </div>
            ))}
          </section>
        )}

        <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
          <div className="grid gap-3 md:grid-cols-6">
            <select value={filters.userType} onChange={(e) => { setFilters({ ...filters, userType: e.target.value }); setCurrentPage(1) }} className="rounded-lg border border-slate-300 px-3 py-2 text-sm">
              <option value="">All Types</option>
              <option value="customer">Customers</option>
              <option value="tutor">Tutors</option>
              <option value="unknown">Unknown</option>
            </select>
            <select value={filters.status} onChange={(e) => { setFilters({ ...filters, status: e.target.value }); setCurrentPage(1) }} className="rounded-lg border border-slate-300 px-3 py-2 text-sm">
              <option value="">All Status</option>
              <option value="pending">Pending</option>
              <option value="contacted">Contacted</option>
              <option value="not_interested">Not Interested</option>
              <option value="invalid">Invalid</option>
            </select>
            <select value={filters.analyzed} onChange={(e) => { setFilters({ ...filters, analyzed: e.target.value }); setCurrentPage(1) }} className="rounded-lg border border-slate-300 px-3 py-2 text-sm">
              <option value="">All Analysis</option>
              <option value="true">Analyzed</option>
              <option value="false">Not Analyzed</option>
            </select>
            <select value={filters.sortBy} onChange={(e) => { setFilters({ ...filters, sortBy: e.target.value }); setCurrentPage(1) }} className="rounded-lg border border-slate-300 px-3 py-2 text-sm">
              <option value="scraped_at">Sort: Scraped At</option>
              <option value="post_date_timestamp">Sort: Post Date</option>
              <option value="confidence_score">Sort: Confidence</option>
              <option value="analyzed_at">Sort: Analyzed At</option>
              <option value="name">Sort: Name</option>
              <option value="status">Sort: Status</option>
            </select>
            <select value={filters.sortOrder} onChange={(e) => { setFilters({ ...filters, sortOrder: e.target.value }); setCurrentPage(1) }} className="rounded-lg border border-slate-300 px-3 py-2 text-sm">
              <option value="desc">Order: Desc</option>
              <option value="asc">Order: Asc</option>
            </select>
            <input type="text" placeholder="Search name, location..." value={filters.q} onChange={(e) => { setFilters({ ...filters, q: e.target.value }); setCurrentPage(1) }} className="rounded-lg border border-slate-300 px-3 py-2 text-sm md:col-span-2" />
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            <button type="button" onClick={analyzeSelected} disabled={selectedIds.size === 0 || analyzingBatch} className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white disabled:bg-slate-400">
              {analyzingBatch ? 'Analyzing...' : `Analyze Selected (${selectedIds.size})`}
            </button>
            <button type="button" onClick={enrichSelected} disabled={selectedIds.size === 0 || enrichingBatch} className="rounded-lg bg-violet-600 px-4 py-2 text-sm font-medium text-white disabled:bg-slate-400">
              {enrichingBatch ? 'Enriching...' : `Enrich Selected (${selectedIds.size})`}
            </button>
            <button type="button" onClick={() => setSelectedIds(new Set())} disabled={selectedIds.size === 0} className="rounded-lg border border-slate-300 px-4 py-2 text-sm text-slate-700 disabled:opacity-40">Clear Selection</button>
            <button type="button" onClick={exportEnriched} disabled={exporting} className="ml-auto rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white disabled:bg-slate-400">
              {exporting ? 'Exporting...' : 'Export Enriched'}
            </button>
          </div>
        </section>

        <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
          <div className="flex items-center gap-4 border-b border-slate-200 bg-slate-50 px-4 py-2 text-[10px] text-slate-500">
            <span className="font-semibold uppercase tracking-wider">Row colors:</span>
            <span className="flex items-center gap-1"><span className="inline-block h-3 w-3 rounded bg-emerald-100 border border-emerald-200" /> &lt; 5 hours</span>
            <span className="flex items-center gap-1"><span className="inline-block h-3 w-3 rounded bg-sky-100 border border-sky-200" /> &lt; 1 day</span>
            <span className="flex items-center gap-1"><span className="inline-block h-3 w-3 rounded bg-amber-100 border border-amber-200" /> &lt; 3 days</span>
          </div>
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-slate-200">
              <thead className="bg-slate-50 text-left text-xs font-semibold uppercase tracking-wide text-slate-600">
                <tr>
                  <th className="px-4 py-3"><input ref={selectAllRef} type="checkbox" checked={allSelected} onChange={toggleSelectAll} className="h-4 w-4 rounded border-slate-300" /></th>
                  <th className="px-4 py-3">Name</th>
                  <th className="px-4 py-3">Type</th>
                  <th className="px-4 py-3">Confidence</th>
                  <th className="px-4 py-3">Location</th>
                  <th className="px-4 py-3">Keyword</th>
                  <th className="px-4 py-3">Status</th>
                  <th className="px-4 py-3">Post</th>
                  <th className="px-4 py-3">Post Date</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {results.length === 0 ? (
                  <tr><td colSpan={9} className="px-4 py-10 text-center text-sm text-slate-500">No leads found.</td></tr>
                ) : (
                  results.map((result) => {
                    const userType = result.user_type || 'unknown'
                    const status = result.status || 'pending'
                    const ageClass = getPostAgeRowClass(result.post_date_timestamp)
                    return (
                      <tr key={result.id} className={`cursor-pointer hover:bg-slate-100 ${ageClass}`} onClick={() => openDetail(result)}>
                        <td className="px-4 py-3" onClick={(e) => e.stopPropagation()}>
                          <input type="checkbox" checked={selectedIds.has(result.id)} onChange={() => toggleRow(result.id)} className="h-4 w-4 rounded border-slate-300" />
                        </td>
                        <td className="px-4 py-3 text-sm">
                          <a href={result.profile_url} target="_blank" rel="noopener noreferrer" onClick={(e) => e.stopPropagation()} className="font-medium text-sky-700 hover:underline">{result.name}</a>
                        </td>
                        <td className="px-4 py-3"><span className={`rounded-full px-2.5 py-1 text-xs font-semibold capitalize ${USER_TYPE_BADGES[userType] || USER_TYPE_BADGES.unknown}`}>{userType}</span></td>
                        <td className="px-4 py-3 text-sm">{result.confidence_score != null ? `${(result.confidence_score * 100).toFixed(0)}%` : '-'}</td>
                        <td className="px-4 py-3 text-sm">{result.location || 'N/A'}</td>
                        <td className="px-4 py-3 text-sm">{result.search_keyword || 'N/A'}</td>
                        <td className="px-4 py-3" onClick={(e) => e.stopPropagation()}>
                          <select value={status} onChange={(e) => updateStatus(result.id, e.target.value)} className={`rounded-full px-2.5 py-1 text-xs font-semibold capitalize ${STATUS_BADGES[status] || STATUS_BADGES.pending}`}>
                            <option value="pending">Pending</option>
                            <option value="contacted">Contacted</option>
                            <option value="not_interested">Not Interested</option>
                            <option value="invalid">Invalid</option>
                          </select>
                        </td>
                        <td className="max-w-[260px] truncate px-4 py-3 text-sm text-slate-600">{result.post_content ? result.post_content.substring(0, 100) : 'N/A'}</td>
                        <td className="px-4 py-3 text-sm text-slate-600 whitespace-nowrap" title={result.post_date_timestamp ? new Date(result.post_date_timestamp).toLocaleString() : (result.post_date || '')}>{result.post_date_timestamp ? formatRelativeTime(result.post_date_timestamp) : (result.post_date || '—')}</td>
                      </tr>
                    )
                  })
                )}
              </tbody>
            </table>
          </div>

          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600">
            <p>Showing {results.length > 0 ? (currentPage - 1) * itemsPerPage + 1 : 0} to {Math.min(currentPage * itemsPerPage, totalItems)} of {totalItems} results</p>
            <div className="flex items-center gap-1">
              <button type="button" onClick={() => setCurrentPage(1)} disabled={currentPage === 1} className="rounded border border-slate-300 bg-white px-2 py-1 disabled:opacity-40">{'<<'}</button>
              <button type="button" onClick={() => setCurrentPage((p) => Math.max(1, p - 1))} disabled={currentPage === 1} className="rounded border border-slate-300 bg-white px-2 py-1 disabled:opacity-40">{'<'}</button>
              {getPageNumbers().map((page, index) => page === '...' ? <span key={`el-${index}`} className="px-2">...</span> : <button key={page} type="button" onClick={() => setCurrentPage(page)} className={`rounded border px-3 py-1 ${currentPage === page ? 'border-slate-900 bg-slate-900 text-white' : 'border-slate-300 bg-white'}`}>{page}</button>)}
              <button type="button" onClick={() => setCurrentPage((p) => Math.min(totalPages, p + 1))} disabled={currentPage === totalPages} className="rounded border border-slate-300 bg-white px-2 py-1 disabled:opacity-40">{'>'}</button>
              <button type="button" onClick={() => setCurrentPage(totalPages)} disabled={currentPage === totalPages} className="rounded border border-slate-300 bg-white px-2 py-1 disabled:opacity-40">{'>>'}</button>
            </div>
            <label className="flex items-center gap-2">
              <span>Items per page:</span>
              <select value={itemsPerPage} onChange={(e) => { setItemsPerPage(Number(e.target.value)); setCurrentPage(1) }} className="rounded border border-slate-300 bg-white px-2 py-1">
                <option value={10}>10</option>
                <option value={20}>20</option>
                <option value={50}>50</option>
                <option value={100}>100</option>
              </select>
            </label>
          </div>
        </section>
      </div>

      <LeadDetailModal
        open={showDetailDialog && !!selectedResult}
        onClose={closeDetail}
        result={selectedResult}
        onResultUpdated={(r) => {
          setSelectedResult(r)
          setResults((prev) => prev.map((row) => (row.id === r.id ? r : row)))
        }}
        onListsRefresh={fetchData}
      />

      {deleteConfirm.isOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4 transition-opacity">
          <div className="w-full max-w-md rounded-2xl bg-white p-6 shadow-xl">
            <h3 className="text-lg font-bold text-slate-900">Confirm Deletion</h3>
            <p className="mt-2 text-sm text-slate-500">
              Are you sure you want to delete {deleteConfirm.type === 'bulk' ? `these ${deleteConfirm.ids.length} selected items` : 'this item'}? This action cannot be undone.
            </p>
            <div className="mt-6 flex justify-end gap-3">
              <button
                onClick={() => setDeleteConfirm({ isOpen: false, ids: [], type: '', isDeleting: false })}
                disabled={deleteConfirm.isDeleting}
                className="rounded-lg px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-100 disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                onClick={executeDelete}
                disabled={deleteConfirm.isDeleting}
                className="rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-50 flex items-center gap-2"
              >
                {deleteConfirm.isDeleting ? (
                  <>
                    <svg className="animate-spin h-4 w-4 text-white" fill="none" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                    </svg>
                    Deleting...
                  </>
                ) : 'Delete'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default App
