"""
This module contains the WebScraper class which implements a high-performance scraping strategy
by conditionally using Playwright (headless Chromium) or a combination of Splash (JS-enabled) plus
aiohttp fallback. A new parameter 'browser_enabled' controls whether Playwright is used exclusively
or not at all.

Features:
  - If browser_enabled is True: Only Playwright is used.
  - If browser_enabled is False: Splash and an aiohttp fallback are raced concurrently.
  - Optional image extraction (controlled by include_images).

Requirements:
  - A running Splash service (e.g., via: docker run -p 8050:8050 scrapinghub/splash)
  - Playwright installed for Python (pip install playwright) and its browsers installed (playwright install)
  - Python packages: aiohttp, playwright, beautifulsoup4, etc.
"""

import random
import re
import time
import asyncio
from urllib.parse import urljoin
from difflib import SequenceMatcher

import aiohttp
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

from app.cache_manager import Cache


def compute_similarity(text1: str, text2: str) -> float:
    """
    Compute similarity between two strings using SequenceMatcher.
    Returns a float between 0 and 1.
    """
    return SequenceMatcher(None, text1, text2).ratio()


class WebScraper:
    """
    WebScraper implements a strategy for fast scraping.
    It uses one of two modes based on the 'browser_enabled' flag:

      - If browser_enabled is True: Only Playwright (headless Chromium) is used.
      - If browser_enabled is False: Splash (JS-enabled via aiohttp) and a fallback aiohttp
        method are raced concurrently.

    Image extraction is optional.
    """

    USER_AGENTS = [
        'Mozilla/5.0 (X11; CrOS x86_64 13729.56.0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.164 Safari/537.36',
    ]

    def __init__(self, query: str = "", include_images: bool = False, browser_enabled: bool = False) -> None:
        """
        Initialize the scraper with:
          - query: Optional text to compare against page content.
          - include_images: If True, image URLs are extracted.
          - browser_enabled: If True, only Playwright is used; if False, Splash + fallback are used.
        """
        self.cache = Cache(expiry=60)
        self.query = query
        self.include_images = include_images
        self.browser_enabled = browser_enabled

    async def get_html_using_playwright(self, url: str) -> str:
        """
        Asynchronously retrieve rendered HTML using Playwright in headless mode.
        Uses "networkidle" waiting and an additional brief sleep to allow full rendering.
        """
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                # Create a browser context with a random user agent.
                context = await browser.new_context(user_agent=random.choice(self.USER_AGENTS))
                page = await context.new_page()
                await page.goto(url, wait_until="networkidle", timeout=15000)
                await asyncio.sleep(1)
                html = await page.content()
                await browser.close()
                return html
        except Exception as e:
            print(f"Playwright error for {url}: {e}")
            return ""

    async def get_html_using_splash(self, url: str) -> str:
        """
        Asynchronously retrieve rendered HTML from a Splash service using aiohttp.
        """
        splash_url = "http://localhost:8050/render.html"
        params = {"url": url, "wait": 2, "timeout": 10}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(splash_url, params=params, timeout=15) as response:
                    if response.status == 200:
                        return await response.text()
        except Exception as e:
            print(f"Splash error for {url}: {e}")
        return ""

    async def fallback_get_html(self, url: str) -> str:
        """
        Asynchronously retrieve HTML using aiohttp as the final fallback.
        """
        try:
            async with aiohttp.ClientSession() as session:
                headers = {"User-Agent": random.choice(self.USER_AGENTS)}
                async with session.get(url, headers=headers, timeout=10) as response:
                    if response.status == 200:
                        return await response.text()
        except Exception as e:
            print(f"Fallback error for {url}: {e}")
        return ""

    async def get_html(self, url: str) -> str:
        """
        Retrieve the HTML content of a page according to the browser_enabled flag:
          - If browser_enabled is True: use only Playwright.
          - Otherwise: concurrently run Splash and fallback methods and return the first nonempty result.
        """
        if self.browser_enabled:
            return await self.get_html_using_playwright(url)
        else:
            tasks = {
                "splash": asyncio.create_task(self.get_html_using_splash(url)),
                "fallback": asyncio.create_task(self.fallback_get_html(url))
            }
            done, pending = await asyncio.wait(tasks.values(), return_when=asyncio.FIRST_COMPLETED, timeout=12)
            for task in pending:
                task.cancel()
            result = ""
            for task in done:
                try:
                    candidate = task.result()
                    if candidate:
                        result = candidate
                        break
                except Exception as e:
                    print(f"Error in task: {e}")
            return result

    def extract_images(self, html: str, base_url: str) -> list:
        """
        Extract up to the first 5 valid image URLs from HTML.
        Converts relative URLs to absolute, skips disallowed extensions (.svg),
        and filters out URLs containing 'logo' or 'icon'.
        """
        if not html:
            return []

        soup = BeautifulSoup(html, 'html.parser')
        images = []
        disallowed_ext = '.svg'
        disallowed_keywords = ['logo', 'icon']

        for img in soup.find_all('img'):
            if len(images) >= 5:
                break

            src = img.get('src')
            if not src:
                continue

            full_url = urljoin(base_url, src)
            lower_url = full_url.lower()

            if lower_url.endswith(disallowed_ext):
                continue

            if any(keyword in lower_url for keyword in disallowed_keywords):
                continue

            images.append(full_url)

        return images

    async def scrape_details(self, url: str) -> dict:
        """
        Asynchronously scrape detailed page information.
        Extracts the title, a snippet, full text, and computes a similarity score against the query.
        Results are cached.
        """
        cached = self.cache.get(url)
        if cached:
            return cached
        html = await self.get_html(url)
        if not html:
            return {"title": "", "url": url, "content": "", "score": 0.0, "raw_content": ""}
        soup = BeautifulSoup(html, 'html.parser')
        title = soup.title.string.strip() if soup.title and soup.title.string else ""
        text = soup.get_text(separator=' ', strip=True)
        cleaned_text = re.sub(r'\s+', ' ', text).strip()
        snippet = cleaned_text[:200] + "..." if len(cleaned_text) > 200 else cleaned_text
        score = compute_similarity(self.query, cleaned_text) if self.query else 0.0
        result = {
            "title": title,
            "url": url,
            "content": snippet,
            "score": round(score, 8),
            "raw_content": cleaned_text
        }
        self.cache.set(url, result)
        return result

    async def scrape(self, url: str) -> dict:
        """
        Asynchronously scrape the main page from 'url':
          - Retrieve rendered HTML using the selected method.
          - Optionally extract image URLs.
          - Scrape the details of the page (without extracting internal links).
        Returns a dictionary with the query, images (if enabled), the page details, and total response time.
        """
        start_time = time.time()
        html = await self.get_html(url)
        if not html:
            return {"error": f"Unable to retrieve main page content for {url}"}
        images = self.extract_images(html, url) if self.include_images else []
        # Directly scrape details from the provided URL without extracting internal links.
        details = await self.scrape_details(url)
        response_time = round(time.time() - start_time, 2)
        return {
            "query": self.query,
            "images": images,
            "result": details,
            "response_time": response_time
        }
