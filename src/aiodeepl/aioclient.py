import asyncio
import random
import time
from typing import Optional, Tuple, Union

import aiohttp
import requests
from aiohttp import ClientResponse, ClientSession
from deepl.exceptions import ConnectionException
from deepl.http_client import HttpClient, _BackoffTimer, min_connection_timeout
from deepl.util import log_info


class _AioBackoffTimer(_BackoffTimer):
    async def sleep_until_deadline(self) -> None:
        await asyncio.sleep(self.get_time_until_deadline())

        # Apply multiplier to current backoff time
        self._backoff = min(
            self._backoff * self.BACKOFF_MULTIPLIER, self.BACKOFF_MAX
        )

        # Get deadline by applying jitter as a proportion of backoff:
        # if jitter is 0.1, then multiply backoff by random value in [0.9, 1.1]
        self._deadline = time.time() + self._backoff * (
            1 + self.BACKOFF_JITTER * random.uniform(-1, 1)
        )
        self._num_retries += 1


class AioHttpClient(HttpClient):
    def __init__(
        self,
        proxy: Optional[str] = None,
        send_platform_info: bool = True,
        verify_ssl: Optional[bool] = None,
    ) -> None:
        self._session = ClientSession()
        if proxy and not isinstance(proxy, str):
            raise ValueError(
                "proxy may be specified as a URL string."
            )
        self._proxy = proxy
        self._verify_ssl = verify_ssl
        self._send_platform_info = send_platform_info
        self._app_info_name: Optional[str] = None
        self._app_info_version: Optional[str] = None
    
    async def close(self) -> None:
        await self._session.close()
    
    async def request_with_backoff(
        self,
        method: str,
        url: str,
        data: Optional[dict],
        json: Optional[dict],
        headers: dict,
        stream: bool = False,
        **kwargs,
    ) -> Tuple[int, Union[str, ClientResponse]]:
        """Makes API request, retrying if necessary, and returns response.

        Return and exceptions are the same as function request()."""
        backoff = _AioBackoffTimer()
        request = self._prepare_request(
            method, url, data, json, headers, **kwargs
        )

        while True:
            response: Optional[Tuple[int, Union[str, ClientResponse]]]
            try:
                response = await self._internal_request(
                    request, stream=stream, timeout=backoff.get_timeout()
                )
                exception = None
            except Exception as e:
                response = None
                exception = e

            if not self._should_retry(
                response, exception, backoff.get_num_retries()
            ):
                if response is not None:
                    return response
                else:
                    raise exception  # type: ignore[misc]

            if exception is not None:
                log_info(
                    f"Encountered a retryable-exception: {str(exception)}"
                )

            log_info(
                f"Starting retry {backoff.get_num_retries() + 1} for request "
                f"{method} {url} after sleeping for "
                f"{backoff.get_time_until_deadline():.2f} seconds."
            )
            await backoff.sleep_until_deadline()
    
    async def request(
        self,
        method: str,
        url: str,
        data: Optional[dict],
        json: Optional[dict],
        headers: dict,
        stream: bool = False,
        **kwargs,
    ) -> Tuple[int, Union[str, ClientResponse]]:
        """Makes API request and returns response content.

        Response is returned as HTTP status code and either content string (if
        stream is False) or response (if stream is True).

        If no response is received will raise ConnectionException."""

        request = self._prepare_request(
            method, url, data, json, headers, **kwargs
        )
        return await self._internal_request(request, stream)
    
    async def _internal_request(
        self,
        request: requests.PreparedRequest,
        stream: bool,
        timeout: float = min_connection_timeout,
        **kwargs,
    ) -> Tuple[int, Union[str, ClientResponse]]:
        try:
            response = await self._session.request(
                request.method, request.url, data=request.body,  # type: ignore
                headers=request.headers, timeout=timeout, **kwargs
            )
            if stream:
                return response.status, response
            else:
                try:
                    return response.status, await response.text(encoding="utf-8")
                finally:
                    response.close()

        except aiohttp.ServerTimeoutError as e:
            message = f"Request timed out: {e}"
            raise ConnectionException(message, should_retry=True) from e
        except aiohttp.ClientConnectionError as e:
            message = f"Connection failed: {e}"
            raise ConnectionException(message, should_retry=True) from e
        except aiohttp.ClientResponseError as e:
            message = f"Request failed: {e}"
            raise ConnectionException(message, should_retry=False) from e
        except Exception as e:
            message = f"Unexpected request failure: {e}"
            raise ConnectionException(message, should_retry=False) from e
