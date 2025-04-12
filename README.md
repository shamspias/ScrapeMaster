# ScrapeMaster

ScrapeMaster is a FastAPI microservice for web scraping that extracts images and page content from a list of URLs using a tiered approach. It first attempts to retrieve JavaScript-rendered pages via Splash (a Scrapy-style solution), then falls back to Selenium (in headless mode) and finally, if needed, to a simple Requests-based scraper. Caching is used to improve performance and avoid re-scraping pages too often.

## Features

- **Tiered Scraping:**  
  - **Splash (JS Enabled):** Uses a Splash service to render pages with JavaScript.
  - **Selenium Fallback:** If Splash fails, falls back to Selenium with Chrome in headless mode.
  - **Requests Fallback:** If Selenium also fails, uses a simple requests-based scraper.
- **Image Extraction:** Scrapes all image URLs from the main page.
- **Content Extraction:** Retrieves internal links and processes each page to extract the title, text snippet, full text, and compute a similarity score based on an optional query.
- **Caching:** Caches results to reduce redundant requests and speed up subsequent scrapes.
- **Flexible HTTP Handling:** Ensures robust scraping even against dynamic or protected web pages.

## Setup Instructions

### Prerequisites

- Python 3.11+
- Google Chrome installed
- [ChromeDriver](https://chromedriver.chromium.org/downloads) corresponding to your version of Chrome
- [Docker](https://docs.docker.com/get-docker/) (required to run Splash)

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

5. **Install Google Chrome & ChromeDriver (if not already installed):**

   **Google Chrome:**
   ```bash
   sudo apt update
   sudo apt install -y google-chrome-stable
   ```

   **ChromeDriver:**
   - Check your Chrome version:
     ```bash
     google-chrome --version
     ```
   - Download the corresponding version of ChromeDriver from [ChromeDriver Downloads](https://chromedriver.chromium.org/downloads)
   - Unzip and install:
     ```bash
     sudo mv chromedriver /usr/local/bin/
     sudo chmod +x /usr/local/bin/chromedriver
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
  "query": "sample query"
}
```

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
      "results": [
        {
          "title": "Page Title",
          "url": "https://example.com/page",
          "content": "Snippet from the page...",
          "score": 0.7654321,
          "raw_content": "Full page text..."
        }
      ],
      "response_time": 12.34
    }
  ]
}
```

If no URLs are provided, the API will respond with a 400 error.

Happy scraping!