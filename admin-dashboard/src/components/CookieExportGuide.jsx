/** Chrome Web Store: Cookie-Editor — used to export facebook.com cookies as JSON */
export const COOKIE_EDITOR_CHROME_URL =
  'https://chromewebstore.google.com/detail/cookie-editor/hlkenndednhfkekhgcdicdfddnkalmdm'

/**
 * @param {'full' | 'compact'} variant — full card for Scraper page; short reminder for modal
 */
export default function CookieExportGuide({ variant = 'full' }) {
  if (variant === 'compact') {
    return (
      <div className="rounded-lg border border-indigo-200 bg-indigo-50/80 px-3 py-2 text-xs text-indigo-950">
        <p className="font-semibold text-indigo-900">Export steps (Cookie-Editor)</p>
        <ol className="mt-1.5 list-decimal space-y-1 pl-4 text-indigo-900/90">
          <li>
            Install{' '}
            <a
              href={COOKIE_EDITOR_CHROME_URL}
              target="_blank"
              rel="noopener noreferrer"
              className="font-medium text-indigo-700 underline hover:text-indigo-900"
            >
              Cookie-Editor
            </a>{' '}
            in Chrome.
          </li>
          <li>Stay logged in on <span className="font-medium">facebook.com</span> in that browser.</li>
          <li>Open the extension → <span className="font-medium">Export</span> → <span className="font-medium">JSON</span>.</li>
          <li>Paste the result here and click Save Cookie.</li>
        </ol>
      </div>
    )
  }

  return (
    <section
      className="rounded-xl border border-indigo-200 bg-gradient-to-br from-indigo-50/90 to-white p-4 shadow-sm"
      aria-labelledby="cookie-export-guide-title"
    >
      <h3 id="cookie-export-guide-title" className="text-sm font-bold text-indigo-950">
        How to copy your Facebook cookie (JSON)
      </h3>
      <p className="mt-1 text-xs text-indigo-900/85">
        The scraper needs a fresh session cookie from the same Facebook account you use in the browser. We recommend the{' '}
        <strong>Cookie-Editor</strong> extension so you can export cookies safely as JSON.
      </p>

      <p className="mt-2 text-xs">
        <a
          href={COOKIE_EDITOR_CHROME_URL}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1 rounded-lg border border-indigo-300 bg-white px-2.5 py-1.5 text-xs font-semibold text-indigo-800 shadow-sm hover:bg-indigo-50"
        >
          Install Cookie-Editor (Chrome Web Store)
          <span aria-hidden="true">↗</span>
        </a>
      </p>

      <ol className="mt-3 list-decimal space-y-2 pl-4 text-xs text-slate-800">
        <li className="pl-1">
          <span className="font-mono text-[11px] text-slate-600">(One-time)</span> Add the extension from the link above and pin it if you like.
        </li>
        <li className="pl-1">
          In Chrome, go to{' '}
          <a
            href="https://www.facebook.com"
            target="_blank"
            rel="noopener noreferrer"
            className="font-medium text-sky-700 underline"
          >
            facebook.com
          </a>{' '}
          and log in to the account the scraper should use.
        </li>
        <li className="pl-1">
          While the tab is on Facebook, click the <strong>Cookie-Editor</strong> extension icon.
        </li>
        <li className="pl-1">
          In Cookie-Editor, open the menu <strong>Export</strong> (or the export control), then choose <strong>JSON</strong> as the format.
        </li>
        <li className="pl-1">
          Copy the JSON (clipboard or select-all). In this dashboard, click <strong>Update Facebook Cookie</strong>, paste into the box, then{' '}
          <strong>Save Cookie</strong>.
        </li>
      </ol>

      <p className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-2.5 py-2 text-[11px] text-amber-950">
        <strong>Security:</strong> Cookies are login credentials. Do not share the JSON or commit it to git. Only paste it into this app’s cookie modal.
      </p>
    </section>
  )
}
