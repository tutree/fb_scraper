import { useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import axios from 'axios'

const API_BASE = '/api/v1'

const USER_TYPE_BADGES = {
  customer: 'bg-sky-100 text-sky-800',
  tutor: 'bg-emerald-100 text-emerald-800',
  unknown: 'bg-slate-100 text-slate-700',
}

const getErrorMessage = (err, fallback) =>
  err?.response?.data?.detail ?? err?.message ?? fallback

export default function CommentsPage() {
  const [comments, setComments] = useState([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [page, setPage] = useState(1)
  const [perPage, setPerPage] = useState(20)
  const [userTypeFilter, setUserTypeFilter] = useState('')
  const [analyzedFilter, setAnalyzedFilter] = useState('')
  const [selectedIds, setSelectedIds] = useState(new Set())
  const [analyzingId, setAnalyzingId] = useState(null)
  const [analyzingBatch, setAnalyzingBatch] = useState(false)
  const [deleteConfirm, setDeleteConfirm] = useState({ isOpen: false, ids: [], type: '', isDeleting: false })
  const [feedback, setFeedback] = useState(null)
  const [selectedComment, setSelectedComment] = useState(null)
  const [showCommentDialog, setShowCommentDialog] = useState(false)
  const selectAllRef = useRef(null)

  useEffect(() => {
    fetchComments()
  }, [page, perPage, userTypeFilter, analyzedFilter])

  const fetchComments = async () => {
    setLoading(true)
    setError(null)
    try {
      const params = new URLSearchParams()
      params.append('skip', (page - 1) * perPage)
      params.append('limit', perPage)
      if (userTypeFilter) params.append('user_type', userTypeFilter)
      if (analyzedFilter) params.append('analyzed', analyzedFilter)
      const res = await axios.get(`${API_BASE}/comments?${params}`)
      const items = Array.isArray(res.data?.items) ? res.data.items : []
      const idsOnPage = new Set(items.map((item) => item.id))
      setComments(items)
      setTotal(res.data?.total ?? 0)
      setSelectedIds((prev) => new Set([...prev].filter((id) => idsOnPage.has(id))))
    } catch (err) {
      setError(getErrorMessage(err, 'Failed to load comments'))
      setComments([])
    } finally {
      setLoading(false)
    }
  }

  const analyzeSingle = async (commentId) => {
    setAnalyzingId(commentId)
    setFeedback(null)
    try {
      const res = await axios.post(`${API_BASE}/comments/${commentId}/analyze`, null, {
        params: { force_reanalyze: true },
      })
      setFeedback({ type: 'success', text: `Comment analyzed: ${res.data?.item?.message || 'Done'}` })
      await fetchComments()
    } catch (err) {
      setFeedback({ type: 'error', text: getErrorMessage(err, 'Failed to analyze comment') })
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
        const res = await axios.post(`${API_BASE}/comments/bulk-delete`, { ids: deleteConfirm.ids })
        setFeedback({ type: 'success', text: res.data?.message || 'Deleted successfully' })
        setSelectedIds(new Set())
      } else {
        const id = deleteConfirm.ids[0];
        const res = await axios.delete(`${API_BASE}/comments/${id}`)
        setFeedback({ type: 'success', text: res.data?.message || 'Deleted successfully' })
        setSelectedIds((prev) => {
          const next = new Set(prev)
          next.delete(id)
          return next
        })
      }
      
      // OPTIMISTIC UPDATE: Refresh UI instantly
      setComments(prev => prev.filter(c => !deleteConfirm.ids.includes(c.id)))

      await fetchComments()
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
      const res = await axios.post(`${API_BASE}/comments/analyze/batch`, {
        comment_ids: ids,
        force_reanalyze: true,
      })
      const { succeeded = 0, skipped = 0, failed = 0 } = res.data || {}
      setFeedback({
        type: failed > 0 ? 'error' : 'success',
        text: `Comment batch complete: ${succeeded} analyzed, ${skipped} skipped, ${failed} failed.`,
      })
      setSelectedIds(new Set())
      await fetchComments()
    } catch (err) {
      setFeedback({ type: 'error', text: getErrorMessage(err, 'Failed to analyze selected comments') })
    } finally {
      setAnalyzingBatch(false)
    }
  }

  const pageIds = useMemo(() => comments.map((comment) => comment.id), [comments])
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

  const openCommentDetail = (comment) => {
    setSelectedComment(comment)
    setShowCommentDialog(true)
  }

  const closeCommentDetail = () => {
    setShowCommentDialog(false)
    setSelectedComment(null)
  }

  const totalPages = Math.max(1, Math.ceil(total / perPage))

  return (
    <div className="min-h-screen bg-gradient-to-b from-slate-100 to-sky-50 px-4 py-8">
      <div className="mx-auto max-w-[1400px] space-y-6">
        <header className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
          <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
            <div>
              <h1 className="text-3xl font-bold text-slate-900">Comments</h1>
              <p className="mt-1 text-sm text-slate-600">Analyze comment authors directly from this table.</p>
            </div>
            <nav className="flex gap-2">
              <Link to="/" className="rounded-md border border-slate-300 px-3 py-2 text-sm text-slate-700 hover:bg-slate-50">Leads</Link>
              <Link to="/comments" className="rounded-md bg-slate-900 px-3 py-2 text-sm font-medium text-white">Comments</Link>
              <Link to="/scraper" className="rounded-md border border-slate-300 px-3 py-2 text-sm text-slate-700 hover:bg-slate-50">Scraper</Link>
            </nav>
          </div>
        </header>

        {feedback && (
          <div className={`rounded-xl border px-4 py-3 text-sm ${feedback.type === 'error' ? 'border-rose-200 bg-rose-50 text-rose-700' : 'border-emerald-200 bg-emerald-50 text-emerald-700'}`}>
            {feedback.text}
          </div>
        )}

        <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
          <div className="flex flex-wrap items-center gap-3">
            <label className="flex items-center gap-2 text-sm text-slate-700">
              <span>User type:</span>
              <select
                value={userTypeFilter}
                onChange={(e) => { setUserTypeFilter(e.target.value); setPage(1) }}
                className="rounded-lg border border-slate-300 px-3 py-2"
              >
                <option value="">All</option>
                <option value="customer">Customer</option>
                <option value="tutor">Tutor</option>
                <option value="unknown">Unknown</option>
              </select>
            </label>
            <label className="flex items-center gap-2 text-sm text-slate-700">
              <span>Analysis:</span>
              <select
                value={analyzedFilter}
                onChange={(e) => { setAnalyzedFilter(e.target.value); setPage(1) }}
                className="rounded-lg border border-slate-300 px-3 py-2"
              >
                <option value="">All</option>
                <option value="true">Analyzed</option>
                <option value="false">Not analyzed</option>
              </select>
            </label>
            <label className="flex items-center gap-2 text-sm text-slate-700">
              <span>Per page:</span>
              <select
                value={perPage}
                onChange={(e) => { setPerPage(Number(e.target.value)); setPage(1) }}
                className="rounded-lg border border-slate-300 px-3 py-2"
              >
                <option value={10}>10</option>
                <option value={20}>20</option>
                <option value={50}>50</option>
                <option value={100}>100</option>
              </select>
            </label>
            <button
              type="button"
              onClick={analyzeSelected}
              disabled={selectedIds.size === 0 || analyzingBatch}
              className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white disabled:bg-slate-400"
            >
              {analyzingBatch ? 'Analyzing...' : `Analyze Selected (${selectedIds.size})`}
            </button>

            <button
              type="button"
              onClick={deleteSelected}
              disabled={selectedIds.size === 0 || deleteConfirm.isDeleting}
              className="rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white disabled:bg-slate-400"
            >
              {deleteConfirm.type === 'bulk' && deleteConfirm.isDeleting ? 'Deleting...' : `Delete Selected (${selectedIds.size})`}
            </button>
            <button
              type="button"
              onClick={() => setSelectedIds(new Set())}
              disabled={selectedIds.size === 0}
              className="rounded-lg border border-slate-300 px-4 py-2 text-sm text-slate-700 disabled:opacity-40"
            >
              Clear Selection
            </button>
          </div>
        </section>

        {error && <p className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</p>}
        {loading && <p className="rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-600">Loading...</p>}

        {!loading && !error && (
          <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-slate-200">
                <thead className="bg-slate-50 text-left text-xs font-semibold uppercase tracking-wide text-slate-600">
                  <tr>
                    <th className="px-4 py-3">
                      <input ref={selectAllRef} type="checkbox" checked={allSelected} onChange={toggleSelectAll} className="h-4 w-4 rounded border-slate-300" />
                    </th>
                    <th className="px-4 py-3">Author</th>
                    <th className="px-4 py-3">Comment</th>
                    <th className="px-4 py-3">Type</th>
                    <th className="px-4 py-3">Score</th>
                    <th className="px-4 py-3">Analysis</th>
                    <th className="px-4 py-3">Time</th>
                    <th className="px-4 py-3">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {comments.length === 0 ? (
                    <tr>
                      <td colSpan={8} className="px-4 py-10 text-center text-sm text-slate-500">No comments found.</td>
                    </tr>
                  ) : (
                    comments.map((comment) => (
                      <tr key={comment.id} className="cursor-pointer hover:bg-slate-50" onClick={() => openCommentDetail(comment)}>
                        <td className="px-4 py-3" onClick={(e) => e.stopPropagation()}>
                          <input type="checkbox" checked={selectedIds.has(comment.id)} onChange={() => toggleRow(comment.id)} className="h-4 w-4 rounded border-slate-300" />
                        </td>
                        <td className="px-4 py-3 text-sm">
                          {comment.author_profile_url ? (
                            <a href={comment.author_profile_url} target="_blank" rel="noopener noreferrer" onClick={(e) => e.stopPropagation()} className="text-sky-700 hover:underline">
                              {comment.author_name || '-'}
                            </a>
                          ) : (comment.author_name || '-')}
                        </td>
                        <td className="max-w-[280px] truncate px-4 py-3 text-sm text-slate-700">{comment.comment_text || '-'}</td>
                        <td className="px-4 py-3">
                          <span className={`rounded-full px-2.5 py-1 text-xs font-semibold capitalize ${USER_TYPE_BADGES[comment.user_type || 'unknown'] || USER_TYPE_BADGES.unknown}`}>
                            {comment.user_type || '-'}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-sm">
                          {comment.confidence_score != null ? `${(comment.confidence_score * 100).toFixed(0)}%` : '-'}
                        </td>
                        <td className="max-w-[320px] truncate px-4 py-3 text-sm text-slate-600">{comment.analysis_message || '-'}</td>
                        <td className="px-4 py-3 text-sm text-slate-600">
                          {comment.comment_timestamp || (comment.scraped_at ? new Date(comment.scraped_at).toLocaleDateString() : '-')}
                        </td>
                        <td className="px-4 py-3" onClick={(e) => e.stopPropagation()}>
                          <button
                            type="button"
                            onClick={() => analyzeSingle(comment.id)}
                            disabled={analyzingId === comment.id || analyzingBatch}
                            className="rounded-md bg-slate-900 px-2.5 py-1.5 text-xs font-medium text-white disabled:bg-slate-400"
                          >
                            {analyzingId === comment.id ? 'Analyzing...' : 'Analyze'}
                          </button>
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
            {total > 0 && (
              <div className="flex flex-wrap items-center justify-center gap-3 border-t border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600">
                <button type="button" onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page <= 1} className="rounded border border-slate-300 bg-white px-3 py-1 disabled:opacity-40">Previous</button>
                <span>Page {page} of {totalPages} ({total} total)</span>
                <button type="button" onClick={() => setPage((p) => Math.min(totalPages, p + 1))} disabled={page >= totalPages} className="rounded border border-slate-300 bg-white px-3 py-1 disabled:opacity-40">Next</button>
              </div>
            )}
          </section>
        )}
      </div>

      {showCommentDialog && selectedComment && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/60 p-4" onClick={closeCommentDetail}>
          <div className="max-h-[85vh] w-full max-w-2xl overflow-y-auto rounded-2xl bg-white shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <div className="sticky top-0 flex items-center justify-between border-b border-slate-200 bg-white px-6 py-4">
              <h3 className="text-lg font-semibold text-slate-900">Comment Details</h3>
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
