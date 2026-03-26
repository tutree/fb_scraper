import { useEffect, useState } from 'react'
import { toast } from 'sonner'

import api from '../api'

const getErrorMessage = (err, fallback) =>
  err?.response?.data?.detail ?? err?.message ?? fallback

function getPostAgeHours(ts) {
  if (!ts) return null
  const diff = Date.now() - new Date(ts).getTime()
  return diff / (1000 * 60 * 60)
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

const getResultEditPayload = (r) => ({
  name: r?.name ?? '',
  location: r?.location ?? '',
  post_content: r?.post_content ?? '',
  post_url: r?.post_url ?? '',
  post_date: r?.post_date ?? '',
  search_keyword: r?.search_keyword ?? '',
  profile_url: r?.profile_url ?? '',
  status: r?.status ?? 'pending',
  user_type: r?.user_type ?? '',
  confidence_score: r?.confidence_score ?? null,
  analysis_message: r?.analysis_message ?? '',
})

const getCommentEditPayload = (c) => ({
  author_name: c?.author_name ?? '',
  author_profile_url: c?.author_profile_url ?? '',
  comment_text: c?.comment_text ?? '',
  comment_timestamp: c?.comment_timestamp ?? '',
  user_type: c?.user_type ?? '',
  confidence_score: c?.confidence_score ?? null,
  analysis_message: c?.analysis_message ?? '',
})

/**
 * Same lead detail + edit + comments + comment sub-modal as the Leads page.
 * `onResultUpdated` receives the latest lead object after load / save / analyze / enrich.
 */
export default function LeadDetailModal({
  open,
  onClose,
  result,
  onResultUpdated,
  onListsRefresh,
}) {
  const [editResultValues, setEditResultValues] = useState(null)
  const [comments, setComments] = useState([])
  const [commentsLoading, setCommentsLoading] = useState(false)
  const [commentsError, setCommentsError] = useState(null)
  const [commentsExpanded, setCommentsExpanded] = useState(false)
  const [commentsLoadedForId, setCommentsLoadedForId] = useState(null)
  const [selectedComment, setSelectedComment] = useState(null)
  const [showCommentDialog, setShowCommentDialog] = useState(false)
  const [editCommentValues, setEditCommentValues] = useState(null)
  const [savingResult, setSavingResult] = useState(false)
  const [savingComment, setSavingComment] = useState(false)
  const [analyzingId, setAnalyzingId] = useState(null)
  const [enrichingId, setEnrichingId] = useState(null)

  useEffect(() => {
    if (!open) return
    document.body.style.overflow = 'hidden'
    return () => {
      document.body.style.overflow = ''
    }
  }, [open])

  useEffect(() => {
    if (!open || !result?.id) return
    setEditResultValues(null)
    setComments([])
    setCommentsError(null)
    setCommentsLoadedForId(null)
    setCommentsExpanded(false)
    setSelectedComment(null)
    setShowCommentDialog(false)
    setEditCommentValues(null)
  }, [open, result?.id])

  const closeCommentDetail = () => {
    setShowCommentDialog(false)
    setSelectedComment(null)
    setEditCommentValues(null)
  }

  const closeAll = () => {
    closeCommentDetail()
    onClose()
  }

  const saveResultEdit = async () => {
    if (!result || !editResultValues) return
    setSavingResult(true)
    try {
      const payload = { ...editResultValues }
      if (payload.confidence_score === '' || payload.confidence_score == null) payload.confidence_score = null
      else payload.confidence_score = Number(payload.confidence_score)
      const res = await api.patch(`/results/${result.id}`, payload)
      onResultUpdated(res.data)
      setEditResultValues(null)
      toast.success('Lead updated.')
      onListsRefresh?.()
    } catch (err) {
      toast.error(getErrorMessage(err, 'Failed to update lead'))
    } finally {
      setSavingResult(false)
    }
  }

  const saveCommentEdit = async () => {
    if (!selectedComment || !editCommentValues) return
    setSavingComment(true)
    try {
      const payload = { ...editCommentValues }
      if (payload.confidence_score === '' || payload.confidence_score == null) payload.confidence_score = null
      else payload.confidence_score = Number(payload.confidence_score)
      const res = await api.patch(`/comments/${selectedComment.id}`, payload)
      setSelectedComment(res.data)
      setComments((prev) => prev.map((c) => (c.id === res.data.id ? res.data : c)))
      setEditCommentValues(null)
      toast.success('Comment updated.')
      onListsRefresh?.()
    } catch (err) {
      toast.error(getErrorMessage(err, 'Failed to update comment'))
    } finally {
      setSavingComment(false)
    }
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

  const analyzeSingle = async (id) => {
    setAnalyzingId(id)
    try {
      const res = await api.post(`/results/${id}/analyze`, null, {
        params: { force_reanalyze: true },
      })
      const item = res.data?.item
      const stagger = item?.geo ? 450 : 0
      if (item?.geo) {
        const g = item.geo
        toast.message('Geo classification', {
          description: `${g.is_us ? 'US' : 'Non-US'} · ${Math.round((Number(g.confidence) || 0) * 100)}% confidence — ${g.reason || ''}`,
          duration: 9000,
        })
      }
      if (item?.removed) {
        setTimeout(() => {
          toast.warning(
            item.removal_reason === 'non_us' ? 'Lead removed (non-US)' : 'Lead removed (not tutoring-related)',
            { description: item.message, duration: 8000 },
          )
        }, stagger)
      } else if (item?.success) {
        setTimeout(() => {
          toast.success('Lead analyzed', { description: item.message || 'Done', duration: 5000 })
        }, stagger)
      }
      onListsRefresh?.()
      if (item?.removed && result?.id === id) {
        closeAll()
        return
      }
      if (result?.id === id && !item?.removed) {
        try {
          const refreshed = await api.get(`/results/${id}`)
          onResultUpdated(refreshed.data)
        } catch {
          /* missing */
        }
      }
    } catch (err) {
      toast.error(getErrorMessage(err, 'Failed to run analysis'))
    } finally {
      setAnalyzingId(null)
    }
  }

  const enrichSingle = async (id) => {
    const row = result
    if (row && (!row.name || !row.location)) {
      const missing = []
      if (!row.name) missing.push('name')
      if (!row.location) missing.push('location')
      toast.error(`Skipped "${row.name || 'Unknown'}": ${missing.join(' and ')} required for enrichment.`)
      return
    }
    setEnrichingId(id)
    try {
      const res = await api.post(`/results/${id}/enrich`, null, {
        params: { force: true },
      })
      const item = res.data?.item
      if (item?.success) {
        toast.success(`Enriched: ${item.message}`)
      } else {
        toast.error(item?.message || 'Enrichment failed')
      }
      onListsRefresh?.()
      if (result?.id === id) {
        const refreshed = await api.get(`/results/${id}`)
        onResultUpdated(refreshed.data)
      }
    } catch (err) {
      toast.error(getErrorMessage(err, 'Failed to enrich contact'))
    } finally {
      setEnrichingId(null)
    }
  }

  if (!open || !result) return null

  return (
    <>
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/50 p-4" onClick={closeAll}>
        <div className="max-h-[90vh] w-full max-w-4xl overflow-y-auto rounded-2xl bg-white shadow-2xl" onClick={(e) => e.stopPropagation()}>
          <div className="sticky top-0 flex items-center justify-between border-b border-slate-200 bg-white px-6 py-4">
            <h2 className="text-xl font-semibold text-slate-900">{editResultValues ? 'Edit Lead' : 'Lead Details'}</h2>
            <div className="flex items-center gap-2">
              {!editResultValues ? (
                <button type="button" onClick={() => setEditResultValues(getResultEditPayload(result))} className="rounded-md border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50">Edit</button>
              ) : null}
              <button type="button" className="rounded-full px-3 py-1 text-xl text-slate-500 hover:bg-slate-100" onClick={closeAll}>×</button>
            </div>
          </div>
          <div className="space-y-4 px-6 py-5 text-sm text-slate-700">
            {editResultValues ? (
              <>
                <div className="grid gap-3 md:grid-cols-2">
                  <label className="block"><span className="font-semibold">Name</span>
                    <input type="text" value={editResultValues.name} onChange={(e) => setEditResultValues((v) => ({ ...v, name: e.target.value }))} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2" />
                  </label>
                  <label className="block"><span className="font-semibold">Keyword</span>
                    <input type="text" value={editResultValues.search_keyword} onChange={(e) => setEditResultValues((v) => ({ ...v, search_keyword: e.target.value }))} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2" />
                  </label>
                  <label className="block"><span className="font-semibold">Location</span>
                    <input type="text" value={editResultValues.location} onChange={(e) => setEditResultValues((v) => ({ ...v, location: e.target.value }))} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2" />
                  </label>
                  <label className="block"><span className="font-semibold">Status</span>
                    <select value={editResultValues.status} onChange={(e) => setEditResultValues((v) => ({ ...v, status: e.target.value }))} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2">
                      <option value="pending">Pending</option>
                      <option value="contacted">Contacted</option>
                      <option value="not_interested">Not Interested</option>
                      <option value="invalid">Invalid</option>
                    </select>
                  </label>
                  <label className="block"><span className="font-semibold">Post Date</span>
                    <input type="text" value={editResultValues.post_date} onChange={(e) => setEditResultValues((v) => ({ ...v, post_date: e.target.value }))} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2" />
                  </label>
                  <label className="block"><span className="font-semibold">User Type</span>
                    <select value={editResultValues.user_type} onChange={(e) => setEditResultValues((v) => ({ ...v, user_type: e.target.value }))} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2">
                      <option value="">—</option>
                      <option value="customer">Customer</option>
                      <option value="tutor">Tutor</option>
                      <option value="unknown">Unknown</option>
                    </select>
                  </label>
                  <label className="block"><span className="font-semibold">Confidence (0–1)</span>
                    <input type="number" min="0" max="1" step="0.01" value={editResultValues.confidence_score ?? ''} onChange={(e) => setEditResultValues((v) => ({ ...v, confidence_score: e.target.value === '' ? null : e.target.value }))} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2" />
                  </label>
                </div>
                <label className="block"><span className="font-semibold">Profile URL</span>
                  <input type="text" value={editResultValues.profile_url} onChange={(e) => setEditResultValues((v) => ({ ...v, profile_url: e.target.value }))} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2" />
                </label>
                <label className="block"><span className="font-semibold">Post URL</span>
                  <input type="text" value={editResultValues.post_url} onChange={(e) => setEditResultValues((v) => ({ ...v, post_url: e.target.value }))} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2" />
                </label>
                <label className="block"><span className="font-semibold">Post content</span>
                  <textarea value={editResultValues.post_content} onChange={(e) => setEditResultValues((v) => ({ ...v, post_content: e.target.value }))} rows={6} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2" />
                </label>
                <label className="block"><span className="font-semibold">Analysis message</span>
                  <textarea value={editResultValues.analysis_message} onChange={(e) => setEditResultValues((v) => ({ ...v, analysis_message: e.target.value }))} rows={4} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2" />
                </label>
              </>
            ) : (
              <>
                <div className="grid gap-3 md:grid-cols-2">
                  <p><span className="font-semibold">Name:</span> {result.name || 'N/A'}</p>
                  <p><span className="font-semibold">Keyword:</span> {result.search_keyword || 'N/A'}</p>
                  <p><span className="font-semibold">Location:</span> {result.location || 'N/A'}</p>
                  <p><span className="font-semibold">Status:</span> {result.status || 'N/A'}</p>
                  <p><span className="font-semibold">Post Date:</span> {result.post_date_timestamp ? `${formatRelativeTime(result.post_date_timestamp)} (${new Date(result.post_date_timestamp).toLocaleString()})` : (result.post_date ?? 'N/A')}</p>
                  <p><span className="font-semibold">User Type:</span> {result.user_type || 'N/A'}</p>
                  <p><span className="font-semibold">Confidence:</span> {result.confidence_score != null ? `${(result.confidence_score * 100).toFixed(0)}%` : 'N/A'}</p>
                  <p className="md:col-span-2"><span className="font-semibold">Analyzed At:</span> {result.analyzed_at ? new Date(result.analyzed_at).toLocaleString() : 'N/A'}</p>
                </div>
                <div>
                  <p><span className="font-semibold">Profile URL:</span></p>
                  {result.profile_url ? (
                    <a href={result.profile_url} target="_blank" rel="noopener noreferrer" className="break-all text-sky-700 hover:underline">{result.profile_url}</a>
                  ) : (
                    <p>N/A</p>
                  )}
                </div>
                <div>
                  <p><span className="font-semibold">Post URL:</span></p>
                  {result.post_url ? (
                    <a href={result.post_url} target="_blank" rel="noopener noreferrer" className="break-all text-sky-700 hover:underline">{result.post_url}</a>
                  ) : (
                    <p>N/A</p>
                  )}
                </div>
                <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 whitespace-pre-wrap">{result.post_content || 'N/A'}</div>
                {result.analysis_message && <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 whitespace-pre-wrap">{result.analysis_message}</div>}

                <div className="rounded-xl border border-violet-200 bg-violet-50 p-4">
                  <div className="mb-3 flex items-center justify-between">
                    <h3 className="text-sm font-semibold text-violet-900">Contact Enrichment</h3>
                    {result.enriched_at && (
                      <span className="text-xs text-violet-500">Enriched {new Date(result.enriched_at).toLocaleString()}</span>
                    )}
                  </div>
                  {!result.enriched_at ? (
                    <p className="text-xs text-violet-700">
                      {result.location
                        ? 'No enrichment data yet. Click "Enrich Contact" to fetch phone numbers, emails and addresses.'
                        : 'Location is required for enrichment. This profile has no location data.'}
                    </p>
                  ) : (
                    <div className="space-y-3 text-sm">
                      {result.enriched_age && (
                        <p><span className="font-semibold text-violet-800">Age:</span> {result.enriched_age}</p>
                      )}
                      {result.enriched_phones?.length > 0 && (
                        <div>
                          <p className="mb-1 font-semibold text-violet-800">Phone Numbers</p>
                          <ul className="space-y-1">
                            {result.enriched_phones.map((p, i) => (
                              <li key={i} className="flex items-center gap-2 rounded-md border border-violet-100 bg-white px-3 py-1.5 text-xs">
                                <span className="font-medium">{p.number}</span>
                                <span className="capitalize text-slate-500">{p.type}</span>
                                {p.is_connected && <span className="rounded-full bg-emerald-100 px-1.5 py-0.5 text-emerald-700">Connected</span>}
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}
                      {result.enriched_emails?.length > 0 && (
                        <div>
                          <p className="mb-1 font-semibold text-violet-800">Emails</p>
                          <ul className="space-y-1">
                            {result.enriched_emails.map((email, i) => (
                              <li key={i} className="rounded-md border border-violet-100 bg-white px-3 py-1.5 text-xs">{email}</li>
                            ))}
                          </ul>
                        </div>
                      )}
                      {result.enriched_addresses?.length > 0 && (
                        <div>
                          <p className="mb-1 font-semibold text-violet-800">Addresses</p>
                          <ul className="space-y-1">
                            {result.enriched_addresses.map((a, i) => (
                              <li key={i} className="rounded-md border border-violet-100 bg-white px-3 py-1.5 text-xs">
                                {[a.street, a.unit, a.city, a.state, a.zip].filter(Boolean).join(', ')}
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}
                      {!result.enriched_phones?.length && !result.enriched_emails?.length && !result.enriched_addresses?.length && (
                        <p className="text-xs text-violet-600">Enrichment ran but no contact data was returned.</p>
                      )}
                    </div>
                  )}
                </div>

                <div>
                  <button
                    type="button"
                    onClick={() => { if (commentsExpanded && commentsLoadedForId === result.id) setCommentsExpanded(false); else fetchComments(result.id); }}
                    disabled={commentsLoading}
                    className="rounded-md border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
                  >
                    {commentsLoading ? 'Loading comments...' : commentsExpanded && commentsLoadedForId === result.id ? 'Hide comments' : 'View comments'}
                  </button>
                  {commentsExpanded && commentsLoadedForId === result.id && (
                    <div className="mt-2 max-h-56 space-y-2 overflow-y-auto rounded-lg border border-slate-200 bg-slate-50 p-2">
                      {commentsError && <p className="text-xs text-rose-700">{commentsError}</p>}
                      {!commentsError && comments.length === 0 && <p className="text-xs text-slate-500">No comments for this post.</p>}
                      {!commentsError && comments.map((comment) => (
                        <button key={comment.id} type="button" onClick={() => { setSelectedComment(comment); setShowCommentDialog(true); }} className="w-full rounded-md border border-slate-200 bg-white p-2 text-left hover:bg-slate-100">
                          <p className="text-xs font-semibold text-slate-800">{comment.author_name || 'Unknown'}</p>
                          <p className="text-xs text-slate-600">{comment.comment_text || ''}</p>
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              </>
            )}
          </div>
          <div className="sticky bottom-0 flex justify-end gap-2 border-t border-slate-200 bg-white px-6 py-4">
            {editResultValues ? (
              <>
                <button type="button" className="rounded-md border border-slate-300 px-4 py-2 text-sm" onClick={() => setEditResultValues(null)} disabled={savingResult}>Cancel</button>
                <button type="button" className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white disabled:bg-slate-400" onClick={saveResultEdit} disabled={savingResult}>{savingResult ? 'Saving...' : 'Save'}</button>
              </>
            ) : (
              <>
                <button type="button" className="rounded-md border border-slate-300 px-4 py-2 text-sm" onClick={closeAll}>Close</button>
                <button type="button" className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white disabled:bg-slate-400" onClick={() => analyzeSingle(result.id)} disabled={analyzingId === result.id}>
                  {analyzingId === result.id ? 'Analyzing...' : 'Analyze'}
                </button>
                <button
                  type="button"
                  className="rounded-md bg-violet-600 px-4 py-2 text-sm font-medium text-white disabled:bg-slate-400"
                  onClick={() => enrichSingle(result.id)}
                  disabled={enrichingId === result.id}
                >
                  {enrichingId === result.id ? 'Enriching...' : result.enriched_at ? 'Re-Enrich Contact' : 'Enrich Contact'}
                </button>
              </>
            )}
          </div>
        </div>
      </div>

      {showCommentDialog && selectedComment && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-slate-950/60 p-4" onClick={closeCommentDetail}>
          <div className="max-h-[85vh] w-full max-w-2xl overflow-y-auto rounded-2xl bg-white shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <div className="sticky top-0 flex items-center justify-between border-b border-slate-200 bg-white px-6 py-4">
              <h3 className="text-lg font-semibold text-slate-900">{editCommentValues ? 'Edit Comment' : 'Comment Analysis'}</h3>
              <div className="flex items-center gap-2">
                {!editCommentValues ? (
                  <button type="button" onClick={() => setEditCommentValues(getCommentEditPayload(selectedComment))} className="rounded-md border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50">Edit</button>
                ) : null}
                <button type="button" className="rounded-full px-3 py-1 text-xl text-slate-500 hover:bg-slate-100" onClick={closeCommentDetail}>×</button>
              </div>
            </div>

            <div className="space-y-4 px-6 py-5 text-sm text-slate-700">
              {editCommentValues ? (
                <>
                  <div className="grid gap-3 md:grid-cols-2">
                    <label className="block"><span className="font-semibold">Author name</span>
                      <input type="text" value={editCommentValues.author_name} onChange={(e) => setEditCommentValues((v) => ({ ...v, author_name: e.target.value }))} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2" />
                    </label>
                    <label className="block"><span className="font-semibold">Timestamp</span>
                      <input type="text" value={editCommentValues.comment_timestamp} onChange={(e) => setEditCommentValues((v) => ({ ...v, comment_timestamp: e.target.value }))} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2" />
                    </label>
                    <label className="block"><span className="font-semibold">Author profile URL</span>
                      <input type="text" value={editCommentValues.author_profile_url} onChange={(e) => setEditCommentValues((v) => ({ ...v, author_profile_url: e.target.value }))} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2" />
                    </label>
                    <label className="block"><span className="font-semibold">User type</span>
                      <select value={editCommentValues.user_type} onChange={(e) => setEditCommentValues((v) => ({ ...v, user_type: e.target.value }))} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2">
                        <option value="">—</option>
                        <option value="customer">Customer</option>
                        <option value="tutor">Tutor</option>
                        <option value="unknown">Unknown</option>
                      </select>
                    </label>
                    <label className="block"><span className="font-semibold">Confidence (0–1)</span>
                      <input type="number" min="0" max="1" step="0.01" value={editCommentValues.confidence_score ?? ''} onChange={(e) => setEditCommentValues((v) => ({ ...v, confidence_score: e.target.value === '' ? null : e.target.value }))} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2" />
                    </label>
                  </div>
                  <label className="block"><span className="font-semibold">Comment text</span>
                    <textarea value={editCommentValues.comment_text} onChange={(e) => setEditCommentValues((v) => ({ ...v, comment_text: e.target.value }))} rows={5} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2" />
                  </label>
                  <label className="block"><span className="font-semibold">Analysis message</span>
                    <textarea value={editCommentValues.analysis_message} onChange={(e) => setEditCommentValues((v) => ({ ...v, analysis_message: e.target.value }))} rows={4} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2" />
                  </label>
                </>
              ) : (
                <>
                  <div className="grid gap-2 md:grid-cols-2">
                    <p><span className="font-semibold">Author:</span> {selectedComment.author_name || 'Unknown'}</p>
                    <p><span className="font-semibold">Timestamp:</span> {selectedComment.comment_timestamp || 'N/A'}</p>
                    <p><span className="font-semibold">Type:</span> {(selectedComment.user_type || 'unknown').toUpperCase()}</p>
                    <p><span className="font-semibold">Confidence:</span> {selectedComment.confidence_score != null ? `${(selectedComment.confidence_score * 100).toFixed(0)}%` : 'N/A'}</p>
                    <p className="md:col-span-2"><span className="font-semibold">Analyzed At:</span> {selectedComment.analyzed_at ? new Date(selectedComment.analyzed_at).toLocaleString() : 'N/A'}</p>
                  </div>
                  <div>
                    <p className="mb-1 font-semibold">Original Comment</p>
                    <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 whitespace-pre-wrap">{selectedComment.comment_text || 'N/A'}</div>
                  </div>
                  <div>
                    <p className="mb-1 font-semibold">Analysis</p>
                    <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 whitespace-pre-wrap">{selectedComment.analysis_message || 'No analysis message available.'}</div>
                  </div>
                </>
              )}
            </div>

            <div className="sticky bottom-0 flex justify-end gap-2 border-t border-slate-200 bg-white px-6 py-4">
              {editCommentValues ? (
                <>
                  <button type="button" className="rounded-md border border-slate-300 px-4 py-2 text-sm" onClick={() => setEditCommentValues(null)} disabled={savingComment}>Cancel</button>
                  <button type="button" className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white disabled:bg-slate-400" onClick={saveCommentEdit} disabled={savingComment}>{savingComment ? 'Saving...' : 'Save'}</button>
                </>
              ) : (
                <button type="button" className="rounded-md border border-slate-300 px-4 py-2 text-sm" onClick={closeCommentDetail}>Close</button>
              )}
            </div>
          </div>
        </div>
      )}
    </>
  )
}
