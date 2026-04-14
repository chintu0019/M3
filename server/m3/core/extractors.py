"""
M3 Content Extractors -- extract text from URLs, PDFs, and other content types.

All heavy/sync operations run via asyncio.to_thread.
"""

import asyncio
import logging

import httpx

logger = logging.getLogger("m3.extractors")


async def extract_url(url: str) -> str:
    """Fetch a URL and extract readable text content."""
    async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
        response = await client.get(url)
        response.raise_for_status()

    import trafilatura

    text = await asyncio.to_thread(trafilatura.extract, response.text)
    return text or ""


async def extract_pdf(pdf_bytes: bytes) -> str:
    """Extract text from PDF bytes."""

    def _extract():
        import io

        import pdfplumber

        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            return "\n\n".join(page.extract_text() or "" for page in pdf.pages)

    return await asyncio.to_thread(_extract)
