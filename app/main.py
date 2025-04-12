"""
main.py
-------
This module sets up the FastAPI application and defines the /scrape endpoint.
Clients submit a POST payload with one or more URLs, an optional query, and an optional flag
to include image extraction (default is false).

To run the service locally:
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
        "Scrape website content using a tiered approach: Splash (JS enabled) first, "
        "then Selenium fallback, and finally, a simple requests-based method. "
        "Optionally include image extraction."
    ),
    version="1.0"
)


class ScrapeRequest(BaseModel):
    urls: Optional[List[str]] = None
    query: Optional[str] = ""
    include_images: Optional[bool] = False  # Default is false, meaning images are not scraped.


@app.post("/scrape", summary="Scrape one or more URLs")
async def scrape_urls(request: ScrapeRequest):
    """
    Endpoint to scrape website(s). Expects a JSON payload with one or more URLs, an optional query,
    and an optional include_images flag. Example payload:

    {
      "urls": ["https://example.com"],
      "query": "sample query",
      "include_images": true
    }

    Returns a JSON response with the following structure:

    {
      "results": [
         {
           "query": "<query provided>",
           "images": [ "img_url_1", "img_url_2", ... ],
           "results": [
              {
                "title": "Page Title",
                "url": "http://example.com/page",
                "content": "Snippet from the page...",
                "score": 0.7654321,
                "raw_content": "Full page text..."
              },
              ...
           ],
           "response_time": 12.34
         },
         ...
      ]
    }

    If no URLs are provided, an HTTP 400 error is returned.
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
