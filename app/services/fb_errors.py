"""Scraper session errors shared across fb_profile_processor and facebook_scraper."""


class CookieExpiredDuringProfileScrape(RuntimeError):
    """
    Profile navigation returned Facebook login/branding (e.g. scraped name is literally
    "Facebook") instead of a real user — session expired mid-scrape. Pending queue
    must be dropped; no row should be saved for this visit.
    """
