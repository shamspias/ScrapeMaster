# ScrapeMaster

ScrapeMaster is a FastAPI microservice for web scraping that extracts images and page content from a list of URLs using a tiered approach. It first attempts to retrieve JavaScript-rendered pages via Splash (a Scrapy-style solution) or a simple aiohttp-based scraper, and if those methods yield empty content, it automatically falls back to using Playwright (headless Chromium) to ensure complete page rendering. Caching is used to improve performance and to avoid re-scraping pages too often.

## Features

- **Tiered Scraping:**  
  - **Splash (JS Enabled):** Uses a Splash service to render pages with JavaScript.
  - **aiohttp Fallback:** If Splash fails, uses an aiohttp-based scraper.
  - **Playwright Auto-Fallback:** If the above methods return empty content, ScrapeMaster automatically falls back to Playwright (headless Chromium) to capture the fully rendered page.
- **Image Extraction:** Optionally scrapes image URLs from the main page.
- **Content Extraction:** Retrieves the title, a text snippet, full page content, and a similarity score based on an optional query for the provided URL(s) without following internal links.
- **Caching:** Caches results to reduce redundant requests and speed up subsequent scrapes.
- **Flexible HTTP Handling:** Ensures robust scraping even against dynamic or protected web pages.

## Setup Instructions

### Prerequisites

- Python 3.11+
- [Docker](https://docs.docker.com/get-docker/) (required to run Splash)
- Playwright installed for Python (see below)

### Installation

1. **Clone the Repository:**
   ```bash
   git clone https://github.com/shamspias/ScrapeMaster.git
   cd ScrapeMaster
   ```

2. **(Optional) Create a Virtual Environment:**
   ```bash
   python -m venv venv
   source venv/bin/activate   # On Windows use: venv\Scripts\activate
   ```

3. **Install Dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Setup Splash:**
   
   Start a Splash server using Docker (if you don’t already have one running):
   ```bash
   docker run -p 8050:8050 scrapinghub/splash
   ```
   This will expose Splash at `http://localhost:8050` for JavaScript rendering.

5. **Install Playwright:**
   ```bash
   pip install playwright
   playwright install
   ```

6. **Run the Application:**
   ```bash
   uvicorn app.main:app --reload
   ```
   The FastAPI service will start at [http://localhost:8000](http://localhost:8000).

## API Usage

Send a POST request to the `/scrape` endpoint with a JSON payload containing an array of URLs and an optional query. For example:

```json
{
  "urls": [
    "https://example.com"
  ],
  "query": "sample query",
  "include_images": true,
  "browser_enabled": false
}
```

- When `browser_enabled` is set to `false` (the default), the service will first attempt to scrape using Splash and aiohttp.  
- If the returned raw content is empty, it automatically falls back to using Playwright, ensuring that pages with heavy JavaScript get rendered.
- When `browser_enabled` is set to `true`, the service directly uses Playwright for page rendering.

The service responds with a JSON object in the following structure:

```json
{
  "results": [
    {
      "query": "sample query",
      "images": [
        "https://example.com/image1.jpg",
        "https://example.com/image2.jpg"
      ],
      "result": {
        "title": "Page Title",
        "url": "https://example.com",
        "content": "Snippet from the page...",
        "score": 0.7654321,
        "raw_content": "Full page text..."
      },
      "response_time": 12.34
    }
  ]
}
```

If no URLs are provided, the API will respond with a 400 error.

Happy scraping!
