"""
main.py
-------
This module sets up the FastAPI microservice with the /scrape endpoint.
Clients send a POST payload with one or more URLs, an optional query,
and an optional include_images flag (default false). The service returns a JSON response.
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
        "Scrape website content using a tiered, concurrent approach: "
        "Splash (JS-enabled) is raced against Selenium and a simple aiohttp fallback. "
        "Internal links are processed concurrently with a semaphore limit, "
        "and image extraction is optional."
    ),
    version="1.0"
)


class ScrapeRequest(BaseModel):
    urls: Optional[List[str]] = None
    query: Optional[str] = ""
    include_images: Optional[bool] = False


@app.post("/scrape", summary="Scrape one or more URLs")
async def scrape_urls(request: ScrapeRequest):
    """
    Endpoint to scrape website(s). Clients provide one or more URLs, an optional query,
    and an optional include_images flag. Example payload:

    {
      "urls": ["https://example.com"],
      "query": "sample query",
      "include_images": true
    }

    Returns a JSON object with:
      - query, images (if enabled), results (each with page details), and response_time.
    """
    if not request.urls or len(request.urls) == 0:
        raise HTTPException(status_code=400, detail="No URLs provided to scrape.")

    tasks = []
    for url in request.urls:
        scraper = WebScraper(query=request.query, include_images=request.include_images)
        tasks.append(scraper.scrape(url))

    results = await asyncio.gather(*tasks)
    return {"results": results}


if __name__ == '__main__':
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
