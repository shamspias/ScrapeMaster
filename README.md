# ScrapeMaster

ScrapeMaster is a FastAPI microservice for web scraping that extracts images and page content from a list of URLs. It
uses Selenium in headless mode with a fallback to Requests when necessary.

## Features

- **Image Extraction:** Scrapes all image URLs from the main page.
- **Content Extraction:** Retrieves and processes internal links, extracting title, text snippet, full text, and a
  similarity score based on an optional query.
- **Flexible HTTP Handling:** Uses Selenium for dynamic content and falls back to Requests for static pages.

## Setup Instructions

### Prerequisites

- Python 3.11+
- Google Chrome installed
- [ChromeDriver](https://chromedriver.chromium.org/downloads) corresponding to your version of Chrome

### Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/shamspias/ScrapeMaster.git
   cd ScrapeMaster
   ```

2. **(Optional) Create a virtual environment:**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows use: venv\Scripts\activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Run the application:**
   ```bash
   uvicorn app.main:app --reload
   ```
   The service will be available at `http://localhost:8000`.

## API Usage

Send a POST request to `/scrape` with a JSON body:

```json
{
  "urls": [
    "https://example.com"
  ],
  "query": "sample query"
}
```

The response will be a JSON object with the scraping results.
int for your web scraping microservice. Happy coding!