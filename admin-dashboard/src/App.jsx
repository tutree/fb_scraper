import { useEffect, useMemo, useRef, useState } from 'react'

import api from './api'



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

function App() {
  const [results, setResults] = useState([])
  const [stats, setStats] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [selectedResult, setSelectedResult] = useState(null)
  const [showDetailDialog, setShowDetailDialog] = useState(false)
  const [filters, setFilters] = useState({
    userType: '',
    status: '',
    analyzed: '',
    sortBy: 'scraped_at',
    sortOrder: 'desc',
    keyword: '',
  })
  const [currentPage, setCurrentPage] = useState(1)
  const [itemsPerPage, setItemsPerPage] = useState(20)
  const [totalItems, setTotalItems] = useState(0)
  const [selectedIds, setSelectedIds] = useState(new Set())
  const [analyzingId, setAnalyzingId] = useState(null)
  const [analyzingBatch, setAnalyzingBatch] = useState(false)
  const [deleteConfirm, setDeleteConfirm] = useState({ isOpen: false, ids: [], type: '', isDeleting: false })
  const [feedback, setFeedback] = useState(null)
  const [comments, setComments] = useState([])
  const [commentsLoading, setCommentsLoading] = useState(false)
  const [commentsError, setCommentsError] = useState(null)
  const [commentsLoadedForId, setCommentsLoadedForId] = useState(null)
  const [commentsExpanded, setCommentsExpanded] = useState(false)
  const [selectedComment, setSelectedComment] = useState(null)
  const [showCommentDialog, setShowCommentDialog] = useState(false)
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

  const updateStatus = async (id, newStatus) => {
    try {
      await api.patch(`/results/${id}`, { status: newStatus })
      await fetchData()
    } catch (err) {
      setFeedback({ type: 'error', text: getErrorMessage(err, 'Failed to update status') })
    }
  }

  const analyzeSingle = async (id) => {
    setAnalyzingId(id)
    setFeedback(null)
    try {
      const res = await api.post(`/results/${id}/analyze`, null, {
        params: { force_reanalyze: true },
      })
      setFeedback({ type: 'success', text: `Lead analyzed: ${res.data?.item?.message || 'Done'}` })
      await fetchData()
      if (selectedResult?.id === id) {
        const refreshed = await api.get(`/results/${id}`)
        setSelectedResult(refreshed.data)
      }
    } catch (err) {
      setFeedback({ type: 'error', text: getErrorMessage(err, 'Failed to run Gemini analysis') })
    } finally {
      setAnalyzingId(null)
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
    setFeedback(null)
    try {
      if (deleteConfirm.type === 'bulk') {
        const res = await api.post(`/results/bulk-delete`, { ids: deleteConfirm.ids })
        setFeedback({ type: 'success', text: res.data?.message || 'Deleted successfully' })
        setSelectedIds(new Set())
      } else {
        const id = deleteConfirm.ids[0];
        const res = await api.delete(`/results/${id}`)
        setFeedback({ type: 'success', text: res.data?.message || 'Deleted successfully' })
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
      setFeedback({ type: 'error', text: getErrorMessage(err, 'Failed to delete') })
    } finally {
      setDeleteConfirm({ isOpen: false, ids: [], type: '', isDeleting: false })
    }
  }

  const analyzeSelected = async () => {
    const ids = [...selectedIds]
    if (ids.length === 0) return
    setAnalyzingBatch(true)
    setFeedback(null)
    try {
      const res = await api.post(`/results/analyze/batch`, {
        result_ids: ids,
        force_reanalyze: true,
      })
      const { succeeded = 0, skipped = 0, failed = 0 } = res.data || {}
      setFeedback({
        type: failed > 0 ? 'error' : 'success',
        text: `Gemini batch complete: ${succeeded} analyzed, ${skipped} skipped, ${failed} failed.`,
      })
      setSelectedIds(new Set())
      await fetchData()
    } catch (err) {
      setFeedback({ type: 'error', text: getErrorMessage(err, 'Failed to run batch analysis') })
    } finally {
      setAnalyzingBatch(false)
    }
  }

  const openDetail = (result) => {
    setSelectedResult(result)
    setShowDetailDialog(true)
    setComments([])
    setCommentsError(null)
    setCommentsLoadedForId(null)
    setCommentsExpanded(false)
  }

  const closeDetail = () => {
    setShowDetailDialog(false)
    setSelectedResult(null)
    setComments([])
    setCommentsError(null)
    setCommentsLoadedForId(null)
    setCommentsExpanded(false)
    setSelectedComment(null)
    setShowCommentDialog(false)
  }

  const openCommentDetail = (comment) => {
    setSelectedComment(comment)
    setShowCommentDialog(true)
  }

  const closeCommentDetail = () => {
    setShowCommentDialog(false)
    setSelectedComment(null)
  }

  const fetchComments = async (resultId) => {
    if (!resultId) return
    setCommentsLoading(true)
    setCommentsError(null)
    try {
      const res = await api.get(`/results/${resultId}/comments`)
      setComments(Array.isArray(res.data) ? res.data : [])
      setCommentsLoadedForId(resultId)
      setCommentsExpanded(true)
    } catch (err) {
      setComments([])
      setCommentsLoadedForId(null)
      setCommentsExpanded(true)
      setCommentsError(getErrorMessage(err, 'Failed to load comments'))
    } finally {
      setCommentsLoading(false)
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
    <div className="min-h-screen bg-gradient-to-b from-slate-100 to-sky-50 px-4 py-8">
      <div className="mx-auto max-w-[1400px] space-y-6">
        {feedback && (
          <div className={`rounded-xl border px-4 py-3 text-sm ${feedback.type === 'error' ? 'border-rose-200 bg-rose-50 text-rose-700' : 'border-emerald-200 bg-emerald-50 text-emerald-700'}`}>
            {feedback.text}
          </div>
        )}

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
              <option value="post_date">Sort: Post Date</option>
              <option value="confidence_score">Sort: Confidence</option>
              <option value="analyzed_at">Sort: Analyzed At</option>
              <option value="name">Sort: Name</option>
              <option value="status">Sort: Status</option>
            </select>
            <select value={filters.sortOrder} onChange={(e) => { setFilters({ ...filters, sortOrder: e.target.value }); setCurrentPage(1) }} className="rounded-lg border border-slate-300 px-3 py-2 text-sm">
              <option value="desc">Order: Desc</option>
              <option value="asc">Order: Asc</option>
            </select>
            <input type="text" placeholder="Search keyword..." value={filters.keyword} onChange={(e) => { setFilters({ ...filters, keyword: e.target.value }); setCurrentPage(1) }} className="rounded-lg border border-slate-300 px-3 py-2 text-sm md:col-span-2" />
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            <button type="button" onClick={analyzeSelected} disabled={selectedIds.size === 0 || analyzingBatch} className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white disabled:bg-slate-400">
              {analyzingBatch ? 'Analyzing...' : `Analyze Selected (${selectedIds.size})`}
            </button>
            <button type="button" onClick={deleteSelected} disabled={selectedIds.size === 0 || deleteConfirm.isDeleting} className="rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white disabled:bg-slate-400">
              {deleteConfirm.type === 'bulk' && deleteConfirm.isDeleting ? 'Deleting...' : `Delete Selected (${selectedIds.size})`}
            </button>
            <button type="button" onClick={() => setSelectedIds(new Set())} disabled={selectedIds.size === 0} className="rounded-lg border border-slate-300 px-4 py-2 text-sm text-slate-700 disabled:opacity-40">Clear Selection</button>
          </div>
        </section>

        <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
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
                  <th className="px-4 py-3">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {results.length === 0 ? (
                  <tr><td colSpan={9} className="px-4 py-10 text-center text-sm text-slate-500">No leads found.</td></tr>
                ) : (
                  results.map((result) => {
                    const userType = result.user_type || 'unknown'
                    const status = result.status || 'pending'
                    return (
                      <tr key={result.id} className="cursor-pointer hover:bg-slate-50" onClick={() => openDetail(result)}>
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
                        <td className="px-4 py-3" onClick={(e) => e.stopPropagation()}>
                          <div className="flex flex-wrap gap-2">
                            <button type="button" onClick={() => analyzeSingle(result.id)} disabled={analyzingId === result.id || analyzingBatch} className="rounded-md bg-slate-900 px-2.5 py-1.5 text-xs font-medium text-white disabled:bg-slate-400">
                              {analyzingId === result.id ? 'Analyzing...' : 'Analyze'}
                            </button>
                            {result.post_url ? <a href={result.post_url} target="_blank" rel="noopener noreferrer" className="rounded-md border border-slate-300 px-2.5 py-1.5 text-xs">View Post</a> : <span className="text-xs text-slate-400">No URL</span>}
                          </div>
                        </td>
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

      {showDetailDialog && selectedResult && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/50 p-4" onClick={closeDetail}>
          <div className="max-h-[90vh] w-full max-w-4xl overflow-y-auto rounded-2xl bg-white shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <div className="sticky top-0 flex items-center justify-between border-b border-slate-200 bg-white px-6 py-4">
              <h2 className="text-xl font-semibold text-slate-900">Lead Details</h2>
              <button type="button" className="rounded-full px-3 py-1 text-xl text-slate-500 hover:bg-slate-100" onClick={closeDetail}>x</button>
            </div>
            <div className="space-y-4 px-6 py-5 text-sm text-slate-700">
              <div className="grid gap-3 md:grid-cols-2">
                <p><span className="font-semibold">Name:</span> {selectedResult.name || 'N/A'}</p>
                <p><span className="font-semibold">Keyword:</span> {selectedResult.search_keyword || 'N/A'}</p>
                <p><span className="font-semibold">Location:</span> {selectedResult.location || 'N/A'}</p>
                <p><span className="font-semibold">Status:</span> {selectedResult.status || 'N/A'}</p>
                <p><span className="font-semibold">Post Date:</span> {selectedResult.post_date ?? 'N/A'}</p>
                <p className="md:col-span-2"><span className="font-semibold">Analyzed At:</span> {selectedResult.analyzed_at ? new Date(selectedResult.analyzed_at).toLocaleString() : 'N/A'}</p>
              </div>
              <div>
                <p><span className="font-semibold">Profile URL:</span></p>
                {selectedResult.profile_url ? (
                  <a
                    href={selectedResult.profile_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="break-all text-sky-700 hover:underline"
                  >
                    {selectedResult.profile_url}
                  </a>
                ) : (
                  <p>N/A</p>
                )}
              </div>
              <div>
                <p><span className="font-semibold">Post URL:</span></p>
                {selectedResult.post_url ? (
                  <a
                    href={selectedResult.post_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="break-all text-sky-700 hover:underline"
                  >
                    {selectedResult.post_url}
                  </a>
                ) : (
                  <p>N/A</p>
                )}
              </div>
              <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 whitespace-pre-wrap">{selectedResult.post_content || 'N/A'}</div>
              {selectedResult.analysis_message && <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 whitespace-pre-wrap">{selectedResult.analysis_message}</div>}
              <div>
                <button
                  type="button"
                  onClick={() => {
                    if (commentsExpanded && commentsLoadedForId === selectedResult.id) {
                      setCommentsExpanded(false)
                    } else {
                      fetchComments(selectedResult.id)
                    }
                  }}
                  disabled={commentsLoading}
                  className="rounded-md border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
                >
                  {commentsLoading
                    ? 'Loading comments...'
                    : commentsExpanded && commentsLoadedForId === selectedResult.id
                      ? 'Hide comments'
                      : 'View comments'}
                </button>
                {commentsExpanded && commentsLoadedForId === selectedResult.id && (
                  <div className="mt-2 max-h-56 space-y-2 overflow-y-auto rounded-lg border border-slate-200 bg-slate-50 p-2">
                    {commentsError && <p className="text-xs text-rose-700">{commentsError}</p>}
                    {!commentsError && comments.length === 0 && <p className="text-xs text-slate-500">No comments for this post.</p>}
                    {!commentsError && comments.map((comment) => (
                      <button
                        key={comment.id}
                        type="button"
                        onClick={() => openCommentDetail(comment)}
                        className="w-full rounded-md border border-slate-200 bg-white p-2 text-left hover:bg-slate-100"
                      >
                        <p className="text-xs font-semibold text-slate-800">{comment.author_name || 'Unknown'}</p>
                        <p className="text-xs text-slate-600">{comment.comment_text || ''}</p>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </div>
            <div className="sticky bottom-0 flex justify-end gap-2 border-t border-slate-200 bg-white px-6 py-4">
              <button type="button" className="rounded-md border border-slate-300 px-4 py-2 text-sm" onClick={closeDetail}>Close</button>
              <button type="button" className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white disabled:bg-slate-400" onClick={() => analyzeSingle(selectedResult.id)} disabled={analyzingId === selectedResult.id || analyzingBatch}>
                {analyzingId === selectedResult.id ? 'Analyzing...' : 'Analyze with Gemini'}
              </button>
            </div>
          </div>
        </div>
      )}

      {showCommentDialog && selectedComment && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-slate-950/60 p-4" onClick={closeCommentDetail}>
          <div className="max-h-[85vh] w-full max-w-2xl overflow-y-auto rounded-2xl bg-white shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <div className="sticky top-0 flex items-center justify-between border-b border-slate-200 bg-white px-6 py-4">
              <h3 className="text-lg font-semibold text-slate-900">Comment Analysis</h3>
              <button type="button" className="rounded-full px-3 py-1 text-xl text-slate-500 hover:bg-slate-100" onClick={closeCommentDetail}>x</button>
            </div>

            <div className="space-y-4 px-6 py-5 text-sm text-slate-700">
              <div className="grid gap-2 md:grid-cols-2">
                <p><span className="font-semibold">Author:</span> {selectedComment.author_name || 'Unknown'}</p>
                <p><span className="font-semibold">Timestamp:</span> {selectedComment.comment_timestamp || 'N/A'}</p>
                <p><span className="font-semibold">Type:</span> {(selectedComment.user_type || 'unknown').toUpperCase()}</p>
                <p><span className="font-semibold">Confidence:</span> {selectedComment.confidence_score != null ? `${(selectedComment.confidence_score * 100).toFixed(0)}%` : 'N/A'}</p>
                <p className="md:col-span-2"><span className="font-semibold">Analyzed At:</span> {selectedComment.analyzed_at ? new Date(selectedComment.analyzed_at).toLocaleString() : 'N/A'}</p>
              </div>

              <div>
                <p className="mb-1 font-semibold">Original Comment</p>
                <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 whitespace-pre-wrap">
                  {selectedComment.comment_text || 'N/A'}
                </div>
              </div>

              <div>
                <p className="mb-1 font-semibold">Analysis</p>
                <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 whitespace-pre-wrap">
                  {selectedComment.analysis_message || 'No analysis message available.'}
                </div>
              </div>
            </div>

            <div className="sticky bottom-0 flex justify-end border-t border-slate-200 bg-white px-6 py-4">
              <button type="button" className="rounded-md border border-slate-300 px-4 py-2 text-sm" onClick={closeCommentDetail}>Close</button>
            </div>
          </div>
        </div>
      )}

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
