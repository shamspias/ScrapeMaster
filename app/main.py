"""
This module sets up the FastAPI microservice with the /scrape endpoint.
Clients send a POST payload including one or more URLs, an optional query,
an optional include_images flag (default false), and a browser_enabled flag.
If browser_enabled is true, the service uses only Selenium; if false, it uses Splash and fallback.
Multiple URLs are processed in parallel.

To run locally:
   uvicorn app.main:app --reload
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Optional
import asyncio

from app.scraper import WebScraper

app = FastAPI(
    title="Web Scraper Microservice",
    description=(
        "Scrape website content using a tiered, concurrent approach. "
        "If browser_enabled is true, only Selenium is used; otherwise, Splash and fallback methods are used. "
        "Internal links are processed concurrently and image extraction is optional."
    ),
    version="1.0"
)


class ScrapeRequest(BaseModel):
    urls: Optional[List[str]] = None
    query: Optional[str] = ""
    include_images: Optional[bool] = False
    browser_enabled: Optional[bool] = False  # If true, use only Selenium; if false, use Splash + fallback.


@app.post("/scrape", summary="Scrape one or more URLs")
async def scrape_urls(request: ScrapeRequest):
    """
    Endpoint to scrape website(s). Clients provide one or more URLs, an optional query,
    an optional include_images flag, and an optional browser_enabled flag.

    Example payload:
    {
      "urls": ["https://example.com"],
      "query": "sample query",
      "include_images": true,
      "browser_enabled": true
    }

    Returns a JSON object with:
      - query, images (if enabled), results (each with page details), and response_time.
    """
    if not request.urls or len(request.urls) == 0:
        raise HTTPException(status_code=400, detail="No URLs provided to scrape.")

    tasks = []
    # Process each URL concurrently.
    for url in request.urls:
        scraper = WebScraper(
            query=request.query,
            include_images=request.include_images,
            browser_enabled=request.browser_enabled
        )
        tasks.append(scraper.scrape(url))

    results = await asyncio.gather(*tasks)
    return {"results": results}


if __name__ == '__main__':
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
