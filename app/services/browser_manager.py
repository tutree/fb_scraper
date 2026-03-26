from playwright.async_api import async_playwright, Browser, Page
from typing import Optional, Dict, Any, List, Tuple
import random
import json
from pathlib import Path
from tenacity import retry, stop_after_attempt, wait_exponential
from ..core.config import settings
from ..services.proxy_manager import ProxyManager
from ..core.logging_config import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Comprehensive anti-detection stealth script
# Injected into every browser context before any page script runs.
# Covers: webdriver flag, plugins, canvas noise, WebGL vendor/renderer,
#         AudioContext noise, chrome runtime, permissions, native toString.
# ---------------------------------------------------------------------------
STEALTH_SCRIPT = """
(function () {
    'use strict';

    // ── 1. Remove webdriver traces ─────────────────────────────────────────
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
    try { delete navigator.__proto__.webdriver; } catch (e) {}

    // ── 2. Realistic navigator.plugins (PDF Viewer objects, not numbers) ───
    try {
        function mkPlugin(name, filename, description, mimes) {
            const p = Object.create(Plugin.prototype);
            Object.defineProperty(p, 'name',        { value: name });
            Object.defineProperty(p, 'filename',    { value: filename });
            Object.defineProperty(p, 'description', { value: description });
            Object.defineProperty(p, 'length',      { value: mimes.length });
            mimes.forEach(function (m, i) {
                const mt = Object.create(MimeType.prototype);
                Object.defineProperty(mt, 'type',          { value: m.type });
                Object.defineProperty(mt, 'description',   { value: m.description });
                Object.defineProperty(mt, 'suffixes',      { value: m.suffixes });
                Object.defineProperty(mt, 'enabledPlugin', { value: p });
                Object.defineProperty(p, i, { value: mt });
            });
            return p;
        }
        var plugins = [
            mkPlugin('PDF Viewer', 'internal-pdf-viewer', 'Portable Document Format',
                [{ type: 'application/pdf', description: 'Portable Document Format', suffixes: 'pdf' },
                 { type: 'text/pdf',        description: 'Portable Document Format', suffixes: 'pdf' }]),
            mkPlugin('Chrome PDF Viewer', 'internal-pdf-viewer', '',
                [{ type: 'application/pdf', description: '', suffixes: 'pdf' },
                 { type: 'text/pdf',        description: '', suffixes: 'pdf' }]),
            mkPlugin('Chromium PDF Plugin', 'internal-pdf-viewer', 'Portable Document Format',
                [{ type: 'application/pdf', description: 'Portable Document Format', suffixes: 'pdf' }])
        ];
        var pa = Object.create(PluginArray.prototype);
        Object.defineProperty(pa, 'length', { value: plugins.length });
        plugins.forEach(function (p, i) {
            Object.defineProperty(pa, i, { value: p });
            Object.defineProperty(pa, p.name, { value: p });
        });
        pa.item      = function (i) { return this[i] || null; };
        pa.namedItem = function (n) { return this[n] || null; };
        Object.defineProperty(navigator, 'plugins', { get: function () { return pa; } });
    } catch (e) {}

    // ── 3. Navigator properties ────────────────────────────────────────────
    Object.defineProperty(navigator, 'languages',          { get: () => ['en-US', 'en'] });
    Object.defineProperty(navigator, 'platform',           { get: () => 'Win32' });
    Object.defineProperty(navigator, 'hardwareConcurrency',{ get: () => 8 });
    Object.defineProperty(navigator, 'deviceMemory',       { get: () => 8 });
    Object.defineProperty(navigator, 'maxTouchPoints',     { get: () => 0 });
    Object.defineProperty(navigator, 'appVersion', {
        get: () => '5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    });
    try {
        Object.defineProperty(navigator, 'connection', {
            get: () => ({ effectiveType: '4g', rtt: 50, downlink: 10.0, saveData: false, onchange: null })
        });
    } catch (e) {}

    // ── 4. Fully-mocked chrome runtime ────────────────────────────────────
    if (!window.chrome) window.chrome = {};
    window.chrome.runtime = {
        id: undefined,
        connect: function () {
            return { onMessage: { addListener: function () {} }, postMessage: function () {}, disconnect: function () {} };
        },
        sendMessage:  function () {},
        onMessage:    { addListener: function () {}, removeListener: function () {} },
        onConnect:    { addListener: function () {}, removeListener: function () {} },
        getPlatformInfo: function (cb) { if (cb) cb({ os: 'win', arch: 'x86-64', nacl_arch: 'x86-64' }); }
    };
    window.chrome.loadTimes = function () {
        return { requestTime: Date.now() / 1000, startLoadTime: Date.now() / 1000,
                 commitLoadTime: Date.now() / 1000, finishDocumentLoadTime: Date.now() / 1000,
                 finishLoadTime: Date.now() / 1000, firstPaintTime: Date.now() / 1000,
                 firstPaintAfterLoadTime: 0, navigationType: 'Other', wasFetchedViaSpdy: false,
                 wasNpnNegotiated: false, npnNegotiatedProtocol: 'unknown', wasAlternateProtocolAvailable: false,
                 connectionInfo: 'unknown' };
    };
    window.chrome.csi = function () {
        return { startE: Date.now(), onloadT: Date.now(), pageT: Date.now() / 1000, tran: 15 };
    };
    window.chrome.app = {
        isInstalled: false,
        InstallState: { DISABLED: 'disabled', INSTALLED: 'installed', NOT_INSTALLED: 'not_installed' },
        RunningState: { CANNOT_RUN: 'cannot_run', READY_TO_RUN: 'ready_to_run', RUNNING: 'running' }
    };

    // ── 5. Permissions API ─────────────────────────────────────────────────
    try {
        var _origQuery = window.navigator.permissions.query.bind(navigator.permissions);
        window.navigator.permissions.query = function (params) {
            if (params && params.name === 'notifications') {
                return Promise.resolve({ state: Notification.permission, onchange: null });
            }
            return _origQuery(params);
        };
    } catch (e) {}

    // ── 6. Canvas fingerprint — add imperceptible per-run noise ───────────
    try {
        var _toDataURL = HTMLCanvasElement.prototype.toDataURL;
        var _getImageData = CanvasRenderingContext2D.prototype.getImageData;
        HTMLCanvasElement.prototype.toDataURL = function () {
            var ctx = this.getContext('2d');
            if (ctx && this.width > 0 && this.height > 0) {
                var img = _getImageData.call(ctx, 0, 0, this.width, this.height);
                for (var i = 0; i < img.data.length; i += 97) {
                    img.data[i] = Math.min(255, img.data[i] + (Math.random() > 0.5 ? 1 : 0));
                }
                ctx.putImageData(img, 0, 0);
            }
            return _toDataURL.apply(this, arguments);
        };
    } catch (e) {}

    // ── 7. WebGL — spoof vendor & renderer ────────────────────────────────
    try {
        var _getParam = WebGLRenderingContext.prototype.getParameter;
        WebGLRenderingContext.prototype.getParameter = function (param) {
            if (param === 37445) return 'Google Inc. (Intel)';
            if (param === 37446) return 'ANGLE (Intel, Intel(R) UHD Graphics 630 Direct3D11 vs_5_0 ps_5_0, D3D11)';
            return _getParam.call(this, param);
        };
    } catch (e) {}
    try {
        var _getParam2 = WebGL2RenderingContext.prototype.getParameter;
        WebGL2RenderingContext.prototype.getParameter = function (param) {
            if (param === 37445) return 'Google Inc. (Intel)';
            if (param === 37446) return 'ANGLE (Intel, Intel(R) UHD Graphics 630 Direct3D11 vs_5_0 ps_5_0, D3D11)';
            return _getParam2.call(this, param);
        };
    } catch (e) {}

    // ── 8. AudioContext — tiny noise on frequency data ────────────────────
    try {
        var _createAnalyser = AudioContext.prototype.createAnalyser;
        AudioContext.prototype.createAnalyser = function () {
            var analyser = _createAnalyser.call(this);
            var _getFloat = analyser.getFloatFrequencyData.bind(analyser);
            analyser.getFloatFrequencyData = function (arr) {
                _getFloat(arr);
                for (var i = 0; i < arr.length; i++) arr[i] += Math.random() * 0.0001 - 0.00005;
            };
            return analyser;
        };
    } catch (e) {}

    // ── 9. iframe contentWindow stealth propagation ───────────────────────
    try {
        var _createElement = document.createElement.bind(document);
        document.createElement = function (tag) {
            var el = _createElement.apply(document, arguments);
            if (typeof tag === 'string' && tag.toLowerCase() === 'iframe') {
                Object.defineProperty(el, 'contentWindow', {
                    get: function () {
                        var cw = HTMLIFrameElement.prototype.__lookupGetter__('contentWindow').call(this);
                        if (!cw) return cw;
                        try { Object.defineProperty(cw.navigator, 'webdriver', { get: () => undefined }); } catch (e) {}
                        return cw;
                    }
                });
            }
            return el;
        };
    } catch (e) {}

    // ── 10. Make overridden functions look native ─────────────────────────
    try {
        var _nativeToString  = Function.prototype.toString;
        var _overridden = [
            HTMLCanvasElement.prototype.toDataURL,
            WebGLRenderingContext.prototype.getParameter,
            navigator.permissions ? navigator.permissions.query : null
        ].filter(Boolean);
        var _overriddenSet = new WeakSet(_overridden);
        Function.prototype.toString = function () {
            if (_overriddenSet.has(this)) {
                return 'function ' + (this.name || '') + '() { [native code] }';
            }
            return _nativeToString.call(this);
        };
    } catch (e) {}

})();
"""


class BrowserManager:
    def __init__(self, proxy_manager: Optional[ProxyManager] = None, headless: bool = True):
        self.proxy_manager = proxy_manager
        self.browser: Optional[Browser] = None
        self.playwright = None

        # Headed mode needed for hover tooltips (date extraction); Xvfb provides display in Docker
        self.headless = settings.HEADLESS

        # Fixed desktop viewport so Facebook serves consistent desktop structure (no mobile/tablet layout)
        self.viewport = {"width": 1920, "height": 1080}
        
        # Randomized user agents
        self.user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15",
        ]

    def _cookie_dirs(self) -> List[Path]:
        """Directories to search for cookie files."""
        return [Path("cookies"), Path("config/cookies")]

    def _normalize_same_site(self, value: Optional[str]) -> str:
        raw = (value or "").strip().lower()
        if raw in {"lax"}:
            return "Lax"
        if raw in {"strict"}:
            return "Strict"
        return "None"

    @staticmethod
    def _get_ci(cookie: Dict[str, Any], *keys: str, default=None):
        """Case-insensitive dict lookup across multiple possible key names."""
        lower_map = {k.lower(): v for k, v in cookie.items()}
        for key in keys:
            val = lower_map.get(key.lower())
            if val is not None:
                return val
        return default

    def _normalize_cookie(self, cookie: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        name = self._get_ci(cookie, "name")
        value = self._get_ci(cookie, "value")
        domain = self._get_ci(cookie, "domain", "host", "host_raw", "hostraw")
        path = self._get_ci(cookie, "path") or "/"

        if not name or value is None or not domain:
            return None

        expires = self._get_ci(cookie, "expires", "expirationdate", "expiry", "expiration")
        if expires is None:
            expires = -1

        try:
            expires = float(expires)
        except Exception:
            expires = -1

        return {
            "name": str(name),
            "value": str(value),
            "domain": str(domain),
            "path": str(path),
            "expires": expires,
            "httpOnly": bool(self._get_ci(cookie, "httponly", "httpOnly", "http_only", default=False)),
            "secure": bool(self._get_ci(cookie, "secure", "isSecure", default=True)),
            "sameSite": self._normalize_same_site(self._get_ci(cookie, "samesite", "sameSite", "same_site")),
        }

    def _parse_storage_state(self, data: Any) -> Optional[Dict[str, Any]]:
        """Accept both Playwright storage_state dict and raw cookie list exports."""
        cookies: List[Dict[str, Any]]
        origins: List[Dict[str, Any]] = []

        if isinstance(data, dict) and isinstance(data.get("cookies"), list):
            cookies = data.get("cookies", [])
            maybe_origins = data.get("origins")
            if isinstance(maybe_origins, list):
                origins = maybe_origins
        elif isinstance(data, list):
            cookies = data
        else:
            return None

        normalized = []
        for cookie in cookies:
            if not isinstance(cookie, dict):
                continue
            item = self._normalize_cookie(cookie)
            if item:
                normalized.append(item)

        if not normalized:
            return None

        return {"cookies": normalized, "origins": origins}

    def _read_json_file(self, file_path: Path) -> Optional[Any]:
        try:
            with open(file_path, "r", encoding="utf-8-sig") as f:
                return json.load(f)
        except Exception as exc:
            logger.warning("Failed to parse cookie file '%s': %s", file_path, exc)
            return None

    def _extract_c_user(self, cookies: List[Dict[str, Any]]) -> Optional[str]:
        for cookie in cookies:
            if cookie.get("name") == "c_user":
                value = cookie.get("value")
                if value:
                    return str(value)
        return None

    def _load_storage_state_for_uid(
        self,
        account_uid: str,
    ) -> Tuple[Optional[Dict[str, Any]], Optional[Path]]:
        """Load storage_state by uid, searching multiple directories and formats."""
        candidates: List[Path] = []
        for directory in self._cookie_dirs():
            if directory.exists():
                candidate = directory / f"{account_uid}.json"
                candidates.append(candidate)
                logger.debug("Cookie candidate: %s (exists=%s)", candidate.absolute(), candidate.exists())
            else:
                logger.debug("Cookie dir does not exist: %s", directory.absolute())

        if not candidates:
            logger.warning("No cookie directories found for account %s", account_uid)

        for file_path in candidates:
            if not file_path.exists():
                logger.debug("Cookie file not found: %s", file_path.absolute())
                continue
            logger.info("Loading cookie file: %s (%d bytes)", file_path, file_path.stat().st_size)
            raw_data = self._read_json_file(file_path)
            if raw_data is None:
                logger.warning("Cookie file unreadable/empty: %s", file_path)
                continue
            storage_state = self._parse_storage_state(raw_data)
            if storage_state:
                return storage_state, file_path
            logger.warning("Cookie file parsed but produced no valid cookies: %s", file_path)

        return None, None

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
    )
    async def get_browser(self) -> Browser:
        """Get or create browser instance with proxy."""
        if not self.browser:
            logger.info("Initializing Playwright...")
            self.playwright = await async_playwright().start()
            logger.info("Playwright started")

            launch_options = {
                "headless": self.headless,  # Use instance configuration (default True)
                "args": [
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-web-security",
                    "--disable-features=IsolateOrigins,site-per-process",
                    "--disable-site-isolation-trials",
                    # Additional stealth args
                    "--disable-infobars",
                    "--window-size=1920,1080",
                    "--start-maximized",
                    "--disable-extensions",
                    "--disable-gpu",
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--disable-default-apps",
                    # Performance optimizations for high-latency proxy
                    "--enable-features=NetworkService,NetworkServiceInProcess",
                    "--enable-quic",  # Enable HTTP/3 for faster loading
                    "--disable-features=IsolateOrigins",  # Reduce connection overhead
                    "--aggressive-cache-discard",
                    "--disable-background-networking",
                    "--disable-sync",
                    "--metrics-recording-only",
                    "--disable-default-apps",
                    "--mute-audio",
                    "--no-first-run",
                    "--disable-backgrounding-occluded-windows",
                    "--disable-renderer-backgrounding",
                    "--disable-background-timer-throttling",
                    "--disable-ipc-flooding-protection",
                ],
            }

            # Add proxy if available
            if self.proxy_manager:
                logger.info("Checking for proxy configuration...")
                proxy_config = self.proxy_manager.get_next_proxy()
                if proxy_config:
                    logger.info(f"Using proxy: {proxy_config}")
                    launch_options["proxy"] = proxy_config
                else:
                    logger.info("No proxy configured, using direct connection")
            else:
                logger.info("Proxy manager not configured")

            logger.info("Launching Chromium browser...")
            self.browser = await self.playwright.chromium.launch(**launch_options)
            logger.info("✓ Browser launched successfully")

            # Quick proxy check (5 second timeout, non-blocking)
            if "proxy" in launch_options:
                try:
                    verify_page = await self.browser.new_page()
                    response = await verify_page.goto("https://api.ipify.org?format=text", wait_until="domcontentloaded", timeout=5000)
                    if response and response.ok:
                        public_ip = await verify_page.inner_text("body")
                        logger.info(f"✓ Proxy working - IP: {public_ip.strip()}")
                    await verify_page.close()
                except Exception as e:
                    logger.warning(f"Proxy check skipped (non-critical): {e}")
                logger.info(f"ℹ Using proxy: {launch_options['proxy'].get('server')}")
            else:
                logger.info(f"ℹ Using direct connection (no proxy)")

        return self.browser

    async def create_page(self) -> Page:
        """Create a new page with enhanced stealth settings."""
        logger.info("Creating new browser page...")
        browser = await self.get_browser()
        
        # Fixed desktop viewport; random user agent only
        viewport = self.viewport
        user_agent = random.choice(self.user_agents)
        logger.info(f"Using viewport: {viewport['width']}x{viewport['height']}")
        logger.debug(f"Using user agent: {user_agent[:50]}...")
        
        # Randomize locale and timezone for more diversity
        locales = ["en-US", "en-GB", "en-CA"]
        timezones = ["America/New_York", "America/Chicago", "America/Los_Angeles", "Europe/London"]
        
        selected_locale = random.choice(locales)
        selected_timezone = random.choice(timezones)
        logger.info(f"Using locale: {selected_locale}, timezone: {selected_timezone}")
        
        logger.info("Creating browser context with stealth settings...")
        
        # Check if we have saved cookies for this session
        from pathlib import Path
        cookies_dir = Path("cookies")
        cookies_dir.mkdir(exist_ok=True)
        
        context = await browser.new_context(
            viewport=viewport,
            user_agent=user_agent,
            locale=selected_locale,
            timezone_id=selected_timezone,
            # Add more realistic browser features
            has_touch=random.choice([True, False]),
            is_mobile=False,
            device_scale_factor=random.choice([1, 1.5, 2]),
            # Enable storage state for cookies
            storage_state=None,  # Will be set per account
        )

        try:
            await context.grant_permissions(
                ["clipboard-read", "clipboard-write"],
                origin="https://www.facebook.com",
            )
            await context.grant_permissions(
                ["clipboard-read", "clipboard-write"],
                origin="https://www.facebook.com",
            )
        except Exception as exc:
            logger.debug("Could not grant clipboard permissions: %s", exc)

        logger.info("Injecting stealth scripts...")
        await context.add_init_script(STEALTH_SCRIPT)

        page = await context.new_page()
        page.set_default_navigation_timeout(90000)
        page.set_default_timeout(90000)
        logger.info("✓ Browser page created with stealth configuration")
        return page
    
    async def create_page_with_cookies(self, account_uid: str) -> Page:
        """Create a page and load saved cookies for the account if available."""
        logger.info(f"Creating browser page for account: {account_uid}")
        browser = await self.get_browser()

        # Fixed desktop viewport; random user agent only
        viewport = self.viewport
        user_agent = random.choice(self.user_agents)
        logger.info(f"Using viewport: {viewport['width']}x{viewport['height']}")

        for directory in self._cookie_dirs():
            try:
                directory.mkdir(exist_ok=True)
            except Exception:
                pass

        storage_state, storage_path = self._load_storage_state_for_uid(account_uid)
        if storage_state:
            c_user = self._extract_c_user(storage_state.get("cookies", []))
            logger.info(
                "Found saved session for %s from %s (cookies=%d, c_user=%s)",
                account_uid,
                storage_path,
                len(storage_state.get("cookies", [])),
                c_user or "unknown",
            )
        else:
            logger.info(
                "No saved session found for %s in cookie dirs: %s",
                account_uid,
                ", ".join(str(d) for d in self._cookie_dirs()),
            )

        # Create context with or without cookies
        context = await browser.new_context(
            viewport=viewport,
            user_agent=user_agent,
            locale="en-US",
            timezone_id="America/New_York",
            has_touch=False,
            is_mobile=False,
            device_scale_factor=1,
            storage_state=storage_state,
        )

        try:
            await context.grant_permissions(
                ["clipboard-read", "clipboard-write"],
                origin="https://www.facebook.com",
            )
            await context.grant_permissions(
                ["clipboard-read", "clipboard-write"],
                origin="https://www.facebook.com",
            )
        except Exception as exc:
            logger.debug("Could not grant clipboard permissions: %s", exc)

        # NOTE: Resource blocking disabled - it was causing timeouts with high-latency proxy
        # Facebook pages need all resources to load properly
        logger.info("Resource blocking disabled - loading all resources for compatibility")

        # Inject comprehensive stealth scripts
        logger.info("Injecting stealth scripts...")
        await context.add_init_script(STEALTH_SCRIPT)

        page = await context.new_page()
        # Set reasonable timeouts for high-latency proxy
        page.set_default_navigation_timeout(120000)  # 2 minutes for navigation
        page.set_default_timeout(60000)  # 1 minute for other operations
        logger.info("Browser page created with stealth configuration")

        # Store context reference for saving cookies later
        page._kiro_context = context
        page._kiro_account_uid = account_uid
        page._kiro_has_loaded_cookies = bool(storage_state)

        return page

    async def close_page_context(self, page: Optional[Page]) -> None:
        """Close a tab and its browser context (e.g. before starting a clean login attempt)."""
        if not page:
            return
        ctx = getattr(page, "_kiro_context", None)
        try:
            await page.close()
        except Exception as exc:
            logger.debug("close_page_context: page.close: %s", exc)
        if ctx:
            try:
                await ctx.close()
            except Exception as exc:
                logger.debug("close_page_context: context.close: %s", exc)

    async def create_fresh_page_for_login(self, account_uid: str) -> Page:
        """
        New browser context with no saved cookies — required so each credential
        sees the real login form instead of checkpoint/redirect from a stale session.
        """
        logger.info("Creating clean browser page for login attempt (UID: %s)", account_uid)
        browser = await self.get_browser()
        viewport = self.viewport
        user_agent = random.choice(self.user_agents)

        context = await browser.new_context(
            viewport=viewport,
            user_agent=user_agent,
            locale="en-US",
            timezone_id="America/New_York",
            has_touch=False,
            is_mobile=False,
            device_scale_factor=1,
            storage_state=None,
        )
        try:
            await context.grant_permissions(
                ["clipboard-read", "clipboard-write"],
                origin="https://www.facebook.com",
            )
            await context.grant_permissions(
                ["clipboard-read", "clipboard-write"],
                origin="https://www.facebook.com",
            )
        except Exception as exc:
            logger.debug("Could not grant clipboard permissions: %s", exc)

        logger.info("Injecting stealth scripts (fresh login context)...")
        await context.add_init_script(STEALTH_SCRIPT)
        page = await context.new_page()
        page.set_default_navigation_timeout(120000)
        page.set_default_timeout(60000)
        page._kiro_context = context
        page._kiro_account_uid = account_uid
        page._kiro_has_loaded_cookies = False
        return page

    async def save_cookies(self, page: Page) -> bool:
        """Save cookies from the page for future use."""
        from pathlib import Path
        import json
        
        try:
            account_uid = getattr(page, '_kiro_account_uid', None)
            context = getattr(page, '_kiro_context', None)
            
            if not account_uid or not context:
                logger.warning("Cannot save cookies: account_uid or context not found")
                return False
            
            cookies_dir = Path("cookies")
            cookies_dir.mkdir(exist_ok=True)
            cookies_file = cookies_dir / f"{account_uid}.json"
            
            # Get storage state (cookies + localStorage)
            storage_state = await context.storage_state()
            
            # Save to file
            with open(cookies_file, 'w') as f:
                json.dump(storage_state, f, indent=2)
            
            logger.info(f"✓ Saved session cookies for {account_uid}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to save cookies: {e}")
            return False

    async def close(self) -> None:
        """Close browser and playwright."""
        if self.browser:
            await self.browser.close()
            self.browser = None
            logger.info("Browser closed")
        if self.playwright:
            await self.playwright.stop()
            self.playwright = None
