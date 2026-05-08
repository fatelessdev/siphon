from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class TransactionIdManager:
    """Manages x-client-transaction-id generation using xclienttransaction.

    Soft-fail: if initialization fails, requests continue without the header.
    No caching — ClientTransaction has no from/to_cache API; we keep the
    soup objects in memory for the session lifetime.
    """

    def __init__(self) -> None:
        self._client_transaction: Any = None
        self._available = False
        self._error: str | None = None

    @property
    def available(self) -> bool:
        return self._available

    @property
    def error(self) -> str | None:
        return self._error

    async def initialize(self, session: Any) -> None:
        try:
            from x_client_transaction import ClientTransaction
            from bs4 import BeautifulSoup

            resp = await session.get("https://x.com")
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")

            # Try to find the ondemand file URL from the page
            ondemand_soup: Any = soup
            try:
                from x_client_transaction.utils import get_ondemand_file_url

                ondemand_url = get_ondemand_file_url(soup)
                ondemand_resp = await session.get(ondemand_url)
                ondemand_resp.raise_for_status()
                ondemand_soup = ondemand_resp.text  # str is fine for 2nd param
            except Exception:
                # Some versions can work without the ondemand file
                logger.debug("Could not fetch ondemand file, using home page only")

            self._client_transaction = ClientTransaction(
                home_page_response=soup,
                ondemand_file_response=ondemand_soup,
            )
            self._available = True
            logger.info("Transaction ID initialized successfully")
        except Exception as e:
            self._error = str(e)
            self._available = False
            logger.warning("Transaction ID initialization failed (stealth degraded): %s", e)

    def get_header(self, url: str = "", method: str = "GET") -> dict[str, str]:
        if not self._available or self._client_transaction is None:
            return {}
        try:
            # ClientTransaction.generate_transaction_id(method, path)
            path = urlparse(url).path if url else "/"
            ct_value = self._client_transaction.generate_transaction_id(method, path)
            return {"x-client-transaction-id": ct_value}
        except Exception as e:
            logger.warning("Transaction ID generation failed: %s", e)
            return {}
