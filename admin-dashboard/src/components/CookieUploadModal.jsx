import CookieExportGuide from './CookieExportGuide'

export default function CookieUploadModal({
  open,
  onClose,
  cookieJsonInput,
  onCookieJsonChange,
  cookieSubmitting,
  onSubmit,
  cookieStatus,
  /** Shown when opened automatically (e.g. cookie expired) */
  urgencyHint,
}) {
  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/60 px-4">
      <div className="w-full max-w-3xl rounded-2xl border border-slate-200 bg-white p-5 shadow-2xl">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="text-xl font-semibold text-slate-900">Update Facebook Cookie</h2>
            <p className="mt-1 text-sm text-slate-600">
              Paste the exported Facebook cookie JSON. The backend will validate it, detect the account from{' '}
              <span className="font-mono">c_user</span>, and update the stored session file.
            </p>
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

        <div className="mt-4 space-y-3">
          <CookieExportGuide variant="compact" />
          <div className="rounded-lg border border-sky-200 bg-sky-50 px-3 py-2 text-xs text-sky-800">
            Accepted formats: raw cookie array from the browser extension, or Playwright{' '}
            <span className="font-mono">storage_state</span> JSON.
          </div>
          <textarea
            value={cookieJsonInput}
            onChange={(e) => onCookieJsonChange(e.target.value)}
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
              onClick={onClose}
              className="rounded-lg border border-slate-300 px-4 py-2 text-sm text-slate-700 hover:bg-slate-50"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={onSubmit}
              disabled={!cookieJsonInput.trim() || cookieSubmitting}
              className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white disabled:bg-slate-400"
            >
              {cookieSubmitting ? 'Saving...' : 'Save Cookie'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
