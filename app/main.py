from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import logging

from app.scraper import PerfectWebScraper


class ScrapeRequest(BaseModel):
    urls: list[str]
    query: str = ""


app = FastAPI(
    title="ScrapeMaster Microservice",
    description="A microservice to scrape website content using Selenium and Requests.",
    version="1.0"
)


@app.post("/scrape", summary="Scrape one or multiple URLs")
async def scrape_urls(request: ScrapeRequest):
    if not request.urls:
        raise HTTPException(status_code=400, detail="No URLs provided to scrape.")

    aggregated_results = []
    for url in request.urls:
        logging.info("Scraping URL: %s", url)
        scraper = PerfectWebScraper(url=url, query=request.query)
        result = scraper.scrape()
        aggregated_results.append(result)

    return {"results": aggregated_results}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
