"""
This module contains the WebScraper class, which implements a tiered approach
for scraping web pages. It first attempts to retrieve rendered HTML via a Splash service
(with JavaScript enabled). If that fails, it falls back to Selenium (Chrome in headless mode)
and, finally, to a simple requests-based scraper. Caching is used to limit repeat requests.

An option is provided to include image extraction, which is disabled by default.
If enabled, the scraper extracts image URLs from the page.

Ensure you have:
  - A running Splash service (e.g., via Docker: docker run -p 8050:8050 scrapinghub/splash)
  - Google Chrome (or Chromium) and ChromeDriver installed for Selenium
  - The required Python packages, as specified in requirements.txt
"""

import random
import re
import time
import asyncio
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin
from difflib import SequenceMatcher

from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from app.cache_manager import Cache


def compute_similarity(text1: str, text2: str) -> float:
    """
    Compute similarity between two strings using SequenceMatcher.
    Returns a float between 0 and 1.
    """
    return SequenceMatcher(None, text1, text2).ratio()


class WebScraper:
    """
    WebScraper implements a multi-tiered strategy for scraping websites:
      1. Splash (JS enabled) - ideal for dynamic pages.
      2. Selenium (Chrome in headless mode) - fallback if Splash fails.
      3. Requests - final fallback if all else fails.

    It extracts page details such as title, text snippet, full text, and computes a similarity score
    against an optional query. Additionally, image extraction can be enabled via the include_images flag.
    """

    # Predefined user agents for rotation.
    USER_AGENTS = [
        'Mozilla/5.0 (X11; CrOS x86_64 13729.56.0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.164 Safari/537.36',
    ]

    def __init__(self, query: str = "", include_images: bool = False) -> None:
        """
        Initialize the scraper with an optional query for similarity scoring and an image extraction flag.
        :param query: Optional string to compare against page content.
        :param include_images: If True, image URLs will be extracted.
        """
        self.executor = ThreadPoolExecutor(max_workers=10)
        self.cache = Cache(expiry=60)  # Cache expiry set to 60 seconds
        self.query = query
        self.include_images = include_images

    def create_driver(self):
        """
        Create and return a Selenium Chrome WebDriver instance in headless mode
        with a randomly selected user agent.
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
        Randomly select and apply one of the predefined user agents.
        """
        try:
            random_user_agent = random.choice(self.USER_AGENTS)
            print(f"Using user agent: {random_user_agent}")
            options.add_argument('user-agent={}'.format(random_user_agent))
        except Exception as e:
            print(f"Error in selecting user agent: {e}")

    async def get_html_using_splash(self, url: str) -> str:
        """
        Attempt to retrieve the HTML of a URL using a Splash service.
        This is executed in a thread to avoid blocking the event loop.
        """
        return await asyncio.to_thread(self._get_html_using_splash, url)

    def _get_html_using_splash(self, url: str) -> str:
        """
        Synchronously request the rendered HTML from Splash.
        Returns an empty string on failure.
        """
        import requests
        splash_url = "http://localhost:8050/render.html"
        params = {"url": url, "wait": 2, "timeout": 10}
        try:
            response = requests.get(splash_url, params=params, timeout=15)
            if response.status_code == 200:
                return response.text
        except Exception as e:
            print(f"Splash error for URL {url}: {e}")
        return ""

    async def get_html(self, url: str) -> str:
        """
        Asynchronously retrieve the HTML content of a page.
          1. Try Splash (JS enabled).
          2. If Splash fails, attempt Selenium.
          3. If Selenium fails, use a fallback requests-based scraper.
        """
        # First, attempt with Splash.
        html = await self.get_html_using_splash(url)
        if html:
            return html

        # Next, try Selenium.
        driver = None
        try:
            driver = self.create_driver()
        except Exception as e:
            print(f"Error initializing Selenium: {e}")
            driver = None

        if driver is not None:
            try:
                driver.get(url)
                WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.TAG_NAME, "body"))
                )
                html = driver.page_source
                driver.quit()
                if html:
                    return html
            except Exception as e:
                print(f"Selenium error for URL {url}: {e}")
                try:
                    driver.quit()
                except Exception:
                    pass

        # Finally, use the fallback method (requests).
        return await self.fallback_get_html(url)

    async def fallback_get_html(self, url: str) -> str:
        """
        Asynchronously retrieve HTML using the requests library as a final fallback.
        """
        return await asyncio.to_thread(self._fallback_get_html, url)

    def _fallback_get_html(self, url: str) -> str:
        """
        Synchronously retrieve HTML using requests.
        """
        import requests
        try:
            headers = {"User-Agent": random.choice(self.USER_AGENTS)}
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                return response.text
        except Exception as e:
            print(f"Fallback requests error for {url}: {e}")
        return ""

    async def extract_links(self, url: str, domain: str, max_links: int = None, max_time: int = None) -> list:
        """
        Asynchronously extract unique internal links from the given URL's HTML.
        'domain' serves as the base for resolving relative paths.
        """
        start_time = time.time()
        html = await self.get_html(url)
        if not html:
            return []
        soup = BeautifulSoup(html, 'html.parser')
        links = set()
        for a in soup.find_all('a', href=True):
            if (max_links and len(links) >= max_links) or (max_time and time.time() - start_time > max_time):
                break
            link = urljoin(domain, a['href'])
            if link.startswith(domain) and "#" not in link:
                links.add(link)
        return list(links)

    async def scrape_text(self, url: str) -> tuple:
        """
        Asynchronously retrieve and clean full text from a given URL.
        Uses caching to avoid duplicate downloads.
        Returns a tuple: (cleaned_text, text_length)
        """
        cached_response = self.cache.get(url)
        if cached_response:
            return cached_response  # Expected tuple: (cleaned_text, length)
        html = await self.get_html(url)
        if not html:
            return None, 0
        soup = BeautifulSoup(html, 'html.parser')
        texts = soup.get_text()
        cleaned_text = re.sub(r'\s+', ' ', texts).strip()
        self.cache.set(url, (cleaned_text, len(cleaned_text)))
        return cleaned_text, len(cleaned_text)

    def extract_images(self, html: str, base_url: str) -> list:
        """
        Extract all image URLs from the HTML by parsing <img> tags and converting them to absolute URLs.
        """
        soup = BeautifulSoup(html, 'html.parser')
        images = []
        for img in soup.find_all('img'):
            src = img.get('src')
            if src:
                full_url = urljoin(base_url, src)
                images.append(full_url)
        return images

    async def scrape_details(self, url: str) -> dict:
        """
        Asynchronously scrape detailed information from a single page.
        Extracts title, a snippet (first 200 characters), full text, and computes a similarity score.
        Results are cached to reduce redundant scraping.

        Returns a dictionary with:
          - title, url, content (snippet), score, raw_content.
        """
        cached_response = self.cache.get(url)
        if cached_response:
            return cached_response
        html = await self.get_html(url)
        if not html:
            return {"title": "", "url": url, "content": "", "score": 0.0, "raw_content": ""}
        soup = BeautifulSoup(html, 'html.parser')
        title = soup.title.string.strip() if soup.title and soup.title.string else ""
        text = soup.get_text(separator=' ', strip=True)
        cleaned_text = re.sub(r'\s+', ' ', text).strip()
        snippet = cleaned_text[:200] + "..." if len(cleaned_text) > 200 else cleaned_text
        similarity_score = compute_similarity(self.query, cleaned_text) if self.query else 0.0
        result = {
            "title": title,
            "url": url,
            "content": snippet,
            "score": round(similarity_score, 8),
            "raw_content": cleaned_text
        }
        self.cache.set(url, result)
        return result

    async def scrape(self, url: str) -> dict:
        """
        Asynchronously scrape the main page at 'url':
          - Retrieve rendered HTML via the tiered methods.
          - Optionally extract image URLs if include_images is True.
          - Extract internal links and scrape detailed information for each linked page.

        Returns a dictionary with:
          - query, images, results (list of detailed page info), and response_time.
        """
        start_time = time.time()
        html = await self.get_html(url)
        if not html:
            return {"error": f"Unable to retrieve main page content for {url}"}
        images = self.extract_images(html, url) if self.include_images else []
        links = await self.extract_links(url, url)
        results = []
        for link in links:
            details = await self.scrape_details(link)
            results.append(details)
        response_time = round(time.time() - start_time, 2)
        return {
            "query": self.query,
            "images": images,
            "results": results,
            "response_time": response_time
        }
