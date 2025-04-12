"""
This module contains the WebScraper class which implements a high-performance scraping strategy
by racing multiple methods concurrently:
  1. Splash (JS-enabled) using aiohttp.
  2. Selenium (Chrome in headless mode) using asyncio.to_thread.
  3. A fallback aiohttp-based request.

A semaphore is used to limit concurrency when processing internal links.
Caching is employed to avoid redundant requests.

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
    WebScraper implements a three-tiered strategy for fast scraping by concurrently launching:
      1. Splash (JS-enabled) via aiohttp.
      2. Selenium (headless Chrome).
      3. A fallback aiohttp request.

    Whichever method returns nonempty HTML first is used. In addition, internal link scraping is done
    concurrently (limited by a semaphore) and image extraction is optional.
    """

    USER_AGENTS = [
        'Mozilla/5.0 (X11; CrOS x86_64 13729.56.0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.164 Safari/537.36',
    ]

    def __init__(self, query: str = "", include_images: bool = False) -> None:
        """
        Initialize the scraper with an optional query (for similarity scoring)
        and a flag to control image extraction.
        """
        self.cache = Cache(expiry=60)
        self.query = query
        self.include_images = include_images
        # Semaphore to limit concurrent processing of internal links.
        self.semaphore = asyncio.Semaphore(SEM_MAX_CONCURRENT)

    def create_driver(self):
        """
        Create and return a Selenium Chrome WebDriver instance (headless) with a random user agent.
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
        Asynchronously retrieve HTML using Selenium.
        This wraps the synchronous _get_html_using_selenium function.
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
        Concurrently launch the three scraping methods (Splash, Selenium, fallback) and return the
        first nonempty result. Any pending tasks are canceled.
        """
        tasks = {
            "splash": asyncio.create_task(self.get_html_using_splash(url)),
            "selenium": asyncio.create_task(self.get_html_using_selenium(url)),
            "fallback": asyncio.create_task(self.fallback_get_html(url))
        }
        done, pending = await asyncio.wait(
            tasks.values(), return_when=asyncio.FIRST_COMPLETED, timeout=12
        )

        # Cancel pending tasks as we only need the first successful result.
        for task in pending:
            task.cancel()

        result = ""
        for task in done:
            try:
                result_candidate = task.result()
                if result_candidate:
                    result = result_candidate
                    break
            except Exception as e:
                print(f"Error in one of the tasks: {e}")
        return result

    async def extract_links(self, url: str, domain: str, max_links: int = None, max_time: int = None) -> list:
        """
        Asynchronously extract unique internal links from the page HTML.
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
        Returns a tuple (cleaned_text, length). Uses cache to avoid duplicate downloads.
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
        Extract image URLs from the HTML by parsing <img> tags and converting them to absolute URLs.
        """
        soup = BeautifulSoup(html, 'html.parser')
        images = []
        for img in soup.find_all('img'):
            src = img.get('src')
            if src:
                images.append(urljoin(base_url, src))
        return images

    async def scrape_details(self, url: str) -> dict:
        """
        Asynchronously scrape detailed page information.
        Extracts the title, text snippet, full text, and computes a similarity score.
        Uses caching to avoid repeated work.
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
        Asynchronously scrape the main page for 'url':
          - Retrieve rendered HTML using the concurrent tiered method.
          - Optionally extract image URLs.
          - Extract internal links and concurrently scrape details for each link (limited by semaphore).
        Returns a dictionary with the query, images, results, and response time.
        """
        start_time = time.time()
        html = await self.get_html(url)
        if not html:
            return {"error": f"Unable to retrieve main page content for {url}"}
        images = self.extract_images(html, url) if self.include_images else []
        links = await self.extract_links(url, url)

        # Use semaphore to limit concurrency when scraping internal link details.
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
