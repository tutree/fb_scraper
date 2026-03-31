import { useEffect, useState } from 'react'
import { toast } from 'sonner'
import api from '../api'
import CookieExportGuide from './CookieExportGuide'

const SLOTS = [1, 2, 3, 4]

const getErrorMessage = (err, fallback) =>
  err?.response?.data?.detail ?? err?.message ?? fallback

const emptySlotMap = () => ({ 1: '', 2: '', 3: '', 4: '' })

export default function CookieUploadModal({
  open,
  onClose,
  cookieStatus,
  urgencyHint,
  onSuccess,
}) {
  const [activeSlot, setActiveSlot] = useState(1)
  const [cookieBySlot, setCookieBySlot] = useState(emptySlotMap)
  const [bindingBySlot, setBindingBySlot] = useState(emptySlotMap)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (!open) return
    setActiveSlot(1)
    setCookieBySlot(emptySlotMap())
    ;(async () => {
      try {
        const res = await api.get('/search/scrape-slots')
        const b = res.data?.bindings || []
        const nextB = emptySlotMap()
        for (let i = 0; i < 4; i++) {
          nextB[i + 1] = b[i] || ''
        }
        setBindingBySlot(nextB)
      } catch {
        setBindingBySlot(emptySlotMap())
      }
    })()
  }, [open])

  if (!open) return null

  const cookieJson = cookieBySlot[activeSlot] ?? ''
  const boundUid = bindingBySlot[activeSlot] ?? ''
  const hasAnyCookie = SLOTS.some((s) => (cookieBySlot[s] || '').trim())

  const setCookieJson = (v) => {
    setCookieBySlot((prev) => ({ ...prev, [activeSlot]: v }))
  }

  const handleSave = async () => {
    if (!hasAnyCookie) {
      toast.error('Paste at least one cookie JSON.')
      return
    }
    setSaving(true)
    try {
      let cookiesSaved = 0

      for (const slot of SLOTS) {
        const cj = (cookieBySlot[slot] || '').trim()
        if (cj) {
          const res = await api.post('/search/cookies', {
            cookie_json: cj,
            slot,
          })
          const uid = res.data?.account_uid
          cookiesSaved += 1
          if (uid) {
            setBindingBySlot((prev) => ({ ...prev, [slot]: uid }))
          }
        }
      }

      if (cookiesSaved) {
        toast.success(`${cookiesSaved} cookie file(s) saved.`)
      }
      setCookieBySlot(emptySlotMap())
      await onSuccess?.()
      onClose()
    } catch (err) {
      toast.error(getErrorMessage(err, 'Save failed'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/60 px-4">
      <div className="w-full max-w-3xl max-h-[90vh] overflow-y-auto rounded-2xl border border-slate-200 bg-white p-5 shadow-2xl">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="text-xl font-semibold text-slate-900">Facebook cookie sessions</h2>
            {urgencyHint && (
              <p className="mt-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
                {urgencyHint}
              </p>
            )}
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border border-slate-300 px-3 py-2 text-sm text-slate-700 hover:bg-slate-50"
          >
            Close
          </button>
        </div>

        <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
          {SLOTS.map((slot) => (
            <button
              key={slot}
              type="button"
              onClick={() => setActiveSlot(slot)}
              className={`flex flex-col items-start rounded-lg px-3 py-2.5 text-left text-sm font-semibold transition ${
                activeSlot === slot
                  ? 'bg-slate-900 text-white shadow-md'
                  : 'border border-slate-200 bg-slate-50 text-slate-800 hover:bg-slate-100'
              }`}
            >
              <span>Account {slot}</span>
              {bindingBySlot[slot] ? (
                <span
                  className={`mt-0.5 font-mono text-[10px] font-normal opacity-90 ${
                    activeSlot === slot ? 'text-slate-200' : 'text-slate-500'
                  }`}
                >
                  UID {bindingBySlot[slot]}
                </span>
              ) : (
                <span
                  className={`mt-0.5 text-[10px] font-normal ${
                    activeSlot === slot ? 'text-slate-300' : 'text-slate-400'
                  }`}
                >
                  empty
                </span>
              )}
            </button>
          ))}
        </div>

        <p className="mt-2 text-xs text-slate-500">
          Editing <span className="font-medium text-slate-700">Account {activeSlot}</span>
          {boundUid ? (
            <>
              {' '}
              · bound UID <span className="font-mono">{boundUid}</span>
            </>
          ) : (
            ' · paste a cookie to bind this tab to a Facebook account'
          )}
        </p>

        <div className="mt-4 space-y-3">
          <CookieExportGuide variant="compact" />
          <div className="rounded-lg border border-sky-200 bg-sky-50 px-3 py-2 text-xs text-sky-800">
            Accepted formats: raw cookie array from Cookie-Editor, or Playwright{' '}
            <span className="font-mono">storage_state</span> JSON.
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-600">
              Cookie JSON for Account {activeSlot}
            </label>
            <textarea
              value={cookieJson}
              onChange={(e) => setCookieJson(e.target.value)}
              rows={16}
              placeholder={`Paste Account ${activeSlot} cookie export here…`}
              className="w-full rounded-xl border border-slate-300 px-3 py-3 font-mono text-sm text-slate-800"
            />
          </div>
        </div>

        <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
          <p className="text-xs text-slate-500">
            Latest saved UID (any): {cookieStatus?.latest_cookie_uid || 'none'}
          </p>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg border border-slate-300 px-4 py-2 text-sm text-slate-700 hover:bg-slate-50"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={handleSave}
              disabled={!hasAnyCookie || saving}
              className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white disabled:bg-slate-400"
            >
              {saving ? 'Saving...' : 'Save cookies'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
