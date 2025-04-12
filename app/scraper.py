import time
import logging
from difflib import SequenceMatcher
from urllib.parse import urljoin, urlparse
from typing import List, Tuple, Optional

import requests
from bs4 import BeautifulSoup

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# A list of alternate user agents for fallback HTTP requests.
ALTERNATIVE_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.131 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.1 Safari/605.1.15",
]


def compute_similarity(text1: str, text2: str) -> float:
    """Compute a similarity score between two strings using SequenceMatcher."""
    return SequenceMatcher(None, text1, text2).ratio()


def is_blocked(content: str) -> bool:
    """Detect common indicators of bot protection in the content."""
    blocked_keywords = ["robot", "bot", "captcha", "unusual traffic", "verify you are human"]
    return any(keyword in content.lower() for keyword in blocked_keywords)


class PerfectWebScraper:
    """
    A web scraper that leverages Selenium (with headless Chrome) and falls back to Requests.

    Given a URL (and an optional query), it:
      - Extracts images on the main page.
      - Gathers internal links.
      - Scrapes each link for title, text snippet, full text, and similarity score.
    """

    def __init__(self, url: str, query: str = "") -> None:
        self.url = url
        self.query = query
        self.results: List[dict] = []
        self.images: List[str] = []
        self.start_time: Optional[float] = None
        self.driver: Optional[webdriver.Chrome] = None

    def _init_driver(self) -> None:
        """Initialize Selenium Chrome WebDriver in headless mode."""
        try:
            logging.info("Initializing Chrome WebDriver in headless mode for %s", self.url)
            chrome_options = Options()
            chrome_options.add_argument('--headless')
            chrome_options.add_argument('--no-sandbox')
            chrome_options.add_argument('--disable-dev-shm-usage')
            self.driver = webdriver.Chrome(options=chrome_options)
            self.driver.set_page_load_timeout(20)
        except WebDriverException as e:
            logging.error("Failed to initialize Chrome WebDriver: %s", e)
            self.driver = None

    def _quit_driver(self) -> None:
        """Quit the Selenium WebDriver if initialized."""
        if self.driver:
            logging.info("Quitting WebDriver for %s", self.url)
            self.driver.quit()
            self.driver = None

    def _get_page_source(self, url: str) -> str:
        """Get a page’s source using Selenium or fallback to Requests."""
        page_source = ""
        if self.driver:
            try:
                logging.info("Loading URL via Selenium: %s", url)
                self.driver.get(url)
                WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((By.TAG_NAME, "body"))
                )
                page_source = self.driver.page_source
                if is_blocked(page_source):
                    logging.warning("Bot protection detected for URL: %s", url)
                    page_source = ""
            except (TimeoutException, WebDriverException) as e:
                logging.error("Selenium error for URL %s: %s", url, e)
        if not page_source:
            logging.info("Falling back to Requests for URL: %s", url)
            for user_agent in ALTERNATIVE_USER_AGENTS:
                try:
                    headers = {"User-Agent": user_agent}
                    response = requests.get(url, headers=headers, timeout=10)
                    if response.status_code == 200:
                        page_source = response.text
                        if is_blocked(page_source):
                            logging.warning("Bot protection with UA '%s' for URL: %s", user_agent, url)
                            page_source = ""
                        else:
                            break
                except requests.RequestException as e:
                    logging.error("Requests error with UA '%s' for URL %s: %s", user_agent, url, e)
        return page_source

    def _extract_images(self, html: str, base_url: str) -> List[str]:
        """Extract and return absolute URLs for all images in the HTML."""
        soup = BeautifulSoup(html, "html.parser")
        images = []
        for img in soup.find_all("img"):
            src = img.get("src")
            if src:
                full_url = urljoin(base_url, src)
                images.append(full_url)
        logging.info("Extracted %d images", len(images))
        return images

    def _extract_links(self, html: str, base_url: str) -> List[str]:
        """Extract unique, same-domain links from the HTML."""
        soup = BeautifulSoup(html, "html.parser")
        links = []
        domain = urlparse(self.url).netloc
        for link in soup.find_all("a", href=True):
            href = link.get("href")
            full_url = urljoin(base_url, href)
            parsed = urlparse(full_url)
            if parsed.netloc.endswith(domain) and not full_url.startswith("javascript"):
                links.append(full_url)
        unique_links = list(set(links))
        logging.info("Extracted %d internal links", len(unique_links))
        return unique_links

    def _get_page_content(self, url: str) -> Tuple[str, str]:
        """Return the title and full text content of the page at the given URL."""
        html = self._get_page_source(url)
        if not html:
            return "", ""
        soup = BeautifulSoup(html, "html.parser")
        title = soup.title.string.strip() if soup.title and soup.title.string else ""
        text = soup.get_text(separator=' ', strip=True)
        return title, text

    def scrape(self) -> dict:
        """
        Perform a full scrape on the provided URL:
          - Extract images from the main page.
          - Retrieve and process internal links.
          - Compute similarity scores (if a query is provided).
          - Return results along with response time.
        """
        self.start_time = time.time()
        self._init_driver()

        main_html = self._get_page_source(self.url)
        if not main_html:
            logging.error("Unable to retrieve content for %s", self.url)
            return {"error": f"Unable to retrieve content for {self.url}"}

        base_url = self.url

        # Extract main page images.
        self.images = self._extract_images(main_html, base_url)

        # Extract internal links.
        links = self._extract_links(main_html, base_url)
        results = []
        for link in links:
            logging.info("Processing link: %s", link)
            title, text = self._get_page_content(link)
            similarity_score = compute_similarity(self.query, text) if self.query and text else 0.0
            snippet = (text[:200] + "...") if len(text) > 200 else text
            results.append({
                "title": title,
                "url": link,
                "content": snippet,
                "score": round(similarity_score, 8),
                "raw_content": text
            })

        response_time = round(time.time() - self.start_time, 2)
        output = {
            "query": self.query,
            "images": self.images,
            "results": results,
            "response_time": response_time
        }
        self._quit_driver()
        logging.info("Scraping completed in %s seconds.", response_time)
        return output
