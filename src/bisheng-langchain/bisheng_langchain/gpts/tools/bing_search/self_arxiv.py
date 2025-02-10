"""Util that calls Arxiv."""

import logging

from langchain_community.utilities.arxiv import ArxivAPIWrapper

logger = logging.getLogger(__name__)


class ArxivAPIWrapperSelf(ArxivAPIWrapper):
    def run(self, query: str) -> str:
        """
        Performs an arxiv search and A single string
        with the publish date, title, authors, and summary
        for each article separated by two newlines.

        If an error occurs or no documents found, error text
        is returned instead. Wrapper for
        https://lukasschwab.me/arxiv.py/index.html#Search

        Args:
            query: a plaintext search query
        """
        try:
            results = self._fetch_results(
                query
            )  # Using helper function to fetch results
        except self.arxiv_exceptions as ex:
            logger.error(f"Arxiv exception: {ex}")  # Added error logging
            return f"Arxiv exception: {ex}"
        docs = [
            f"Published: {result.updated.date()}\n"
            f"Title: {result.title}\n"
            f"Authors: {', '.join(a.name for a in result.authors)}\n"
            f"Summary: {result.summary}"
            f"pdf_url: {result.pdf_url}"
            for result in results
        ]
        if docs:
            return "\n\n".join(docs)[: self.doc_content_chars_max]
        else:
            return "No good Arxiv Result was found"
