"""
This module contains the WebScraper class which implements a high-performance scraping strategy
by conditionally using Selenium (headless Chrome) or a combination of Splash (JS-enabled) plus
aiohttp fallback. A new parameter 'browser_enabled' controls whether Selenium is used exclusively
or not at all.

Features:
  - If browser_enabled is True: Only Selenium is used.
  - If browser_enabled is False: Splash and an aiohttp fallback are raced concurrently.
  - Concurrent processing of internal links via a semaphore.
  - Optional image extraction (controlled by include_images).

Requirements:
  - A running Splash service (e.g., via docker run -p 8050:8050 scrapinghub/splash)
  - Google Chrome (or Chromium) and ChromeDriver installed for Selenium
  - Python packages: aiohttp, selenium, beautifulsoup4, etc.
"""

import random
import re
import time
import asyncio
from urllib.parse import urljoin
from difflib import SequenceMatcher

import aiohttp
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from app.cache_manager import Cache

# Limit concurrent internal link scrapes (tweak as needed)
SEM_MAX_CONCURRENT = 10


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

      - If browser_enabled is True: Only Selenium (Chrome in headless mode) is used.
      - If browser_enabled is False: Splash (JS-enabled via aiohttp) and a fallback aiohttp
        method are raced concurrently (Selenium is not used).

    Internal link extraction is done concurrently (limited by a semaphore), and image extraction
    is optional.
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
          - browser_enabled: If True, only Selenium is used; if False, Selenium is skipped.
        """
        self.cache = Cache(expiry=60)
        self.query = query
        self.include_images = include_images
        self.browser_enabled = browser_enabled
        self.semaphore = asyncio.Semaphore(SEM_MAX_CONCURRENT)

    def create_driver(self):
        """
        Create and return a Selenium Chrome WebDriver instance in headless mode with a random user agent.
        """
        options = Options()
        options.add_argument('--headless')
        options.add_argument('--disable-gpu')
        options.add_argument('--window-size=1920,1080')
        options.add_argument('--disable-extensions')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        self.change_user_agent(options)
        return webdriver.Chrome(options=options)

    def change_user_agent(self, options):
        """
        Randomly choose and apply a user agent to the Selenium options.
        """
        try:
            ua = random.choice(self.USER_AGENTS)
            print(f"Using user agent: {ua}")
            options.add_argument(f'user-agent={ua}')
        except Exception as e:
            print(f"Error setting user agent: {e}")

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

    async def get_html_using_selenium(self, url: str) -> str:
        """
        Asynchronously retrieve HTML using Selenium (wrapped in asyncio.to_thread).
        """
        return await asyncio.to_thread(self._get_html_using_selenium, url)

    def _get_html_using_selenium(self, url: str) -> str:
        """
        Synchronously retrieve HTML using Selenium.
        """
        driver = None
        try:
            driver = self.create_driver()
            driver.get(url)
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
            html = driver.page_source
            driver.quit()
            return html
        except Exception as e:
            print(f"Selenium error for {url}: {e}")
            if driver:
                try:
                    driver.quit()
                except Exception:
                    pass
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
          - If browser_enabled is True: use only Selenium.
          - Otherwise: concurrently run Splash and fallback methods and return the first nonempty result.
        """
        if self.browser_enabled:
            return await self.get_html_using_selenium(url)
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

    async def extract_links(self, url: str, domain: str, max_links: int = None, max_time: int = None) -> list:
        """
        Asynchronously extract unique internal links from the page HTML.
        'domain' is used to resolve relative paths.
        """
        start_time = time.time()
        html = await self.get_html(url)
        if not html:
            return []
        soup = BeautifulSoup(html, 'html.parser')
        links = set()
        for a in soup.find_all('a', href=True):
            if (max_links and len(links) >= max_links) or (max_time and (time.time() - start_time > max_time)):
                break
            link = urljoin(domain, a['href'])
            if link.startswith(domain) and "#" not in link:
                links.add(link)
        return list(links)

    async def scrape_text(self, url: str) -> tuple:
        """
        Asynchronously retrieve and clean full text from a URL.
        Returns a tuple: (cleaned_text, length) using the cache to avoid redundancy.
        """
        cached = self.cache.get(url)
        if cached:
            return cached
        html = await self.get_html(url)
        if not html:
            return None, 0
        soup = BeautifulSoup(html, 'html.parser')
        texts = soup.get_text()
        cleaned = re.sub(r'\s+', ' ', texts).strip()
        self.cache.set(url, (cleaned, len(cleaned)))
        return cleaned, len(cleaned)

    def extract_images(self, html: str, base_url: str) -> list:
        """
        Extract image URLs from the HTML by parsing <img> tags and converting relative URLs to absolute.
        Filters out disallowed extensions (.svg) and URLs containing words like 'logo' or 'icon'.
        Returns up to the last 5 valid image URLs.
        """
        if not html:
            return []

        soup = BeautifulSoup(html, 'html.parser')
        images = []
        disallowed_ext = '.svg'
        disallowed_keywords = ['logo', 'icon']

        for img in soup.find_all('img'):
            src = img.get('src')
            if src:
                full_url = urljoin(base_url, src)
                lower_url = full_url.lower()
                if not lower_url.endswith(disallowed_ext) and not any(
                        keyword in lower_url for keyword in disallowed_keywords):
                    images.append(full_url)

        return images[-5:]  # Return last 5 (or fewer) valid image URLs

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
          - Retrieve rendered HTML using the selected method (browser_enabled flag applied).
          - Optionally extract image URLs.
          - Extract internal links and concurrently scrape details for each link (controlled by a semaphore).
        Returns a dictionary with the query, images (if enabled), results, and total response time.
        """
        start_time = time.time()
        html = await self.get_html(url)
        if not html:
            return {"error": f"Unable to retrieve main page content for {url}"}
        images = self.extract_images(html, url) if self.include_images else []
        links = await self.extract_links(url, url)

        # Concurrency for internal link scraping using a semaphore
        async def safe_scrape(link):
            async with self.semaphore:
                return await self.scrape_details(link)

        tasks = [asyncio.create_task(safe_scrape(link)) for link in links]
        details_list = await asyncio.gather(*tasks)
        response_time = round(time.time() - start_time, 2)
        return {
            "query": self.query,
            "images": images,
            "results": details_list,
            "response_time": response_time
        }
