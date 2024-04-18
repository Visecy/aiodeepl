import asyncio
import json as json_module
import urllib.parse
from typing import Any, BinaryIO, Optional, Tuple, Union

import greenback
from aiohttp import ClientResponse
from deepl import DocumentHandle, util
from deepl.translator import Translator as _Translator
from typing_extensions import Self

from .aioclient import AioHttpClient


class Translator(_Translator):
    """Wrapper for the DeepL API for language translation.

    You must create an instance of Translator to use the DeepL API.

    :param auth_key: Authentication key as found in your DeepL API account.
    :param server_url: (Optional) Base URL of DeepL API, can be overridden e.g.
        for testing purposes.
    :param proxy: (Optional) Proxy server URL string or dictionary containing
        URL strings for the 'http' and 'https' keys. This is passed to the
        underlying requests session, see the requests proxy documentation for
        more information.
    :param send_platform_info: (Optional) boolean that indicates if the client
        library can send basic platform info (python version, OS, http library
        version) to the DeepL API. True = send info, False = only send client
        library version
    :param verify_ssl: (Optional) Controls how requests verifies SSL
        certificates. This is passed to the underlying requests session, see
        the requests verify documentation for more information.
    :param skip_language_check: Deprecated, and now has no effect as the
        corresponding internal functionality has been removed. This parameter
        will be removed in a future version.

    All functions may raise DeepLException or a subclass if a connection error
    occurs.
    """

    def __init__(
        self,
        auth_key: str,
        *,
        server_url: Optional[str] = None,
        proxy: Optional[str] = None,
        send_platform_info: bool = True,
        verify_ssl: Optional[bool] = None,
        skip_language_check: bool = False,
    ) -> None:
        if not auth_key:
            raise ValueError("auth_key must not be empty")

        if server_url is None:
            server_url = (
                self._DEEPL_SERVER_URL_FREE
                if util.auth_key_is_free_account(auth_key)
                else self._DEEPL_SERVER_URL
            )

        self._server_url = server_url
        self._client = AioHttpClient(
            proxy, send_platform_info, verify_ssl
        )
        self.headers = {"Authorization": f"DeepL-Auth-Key {auth_key}"}

    def __del__(self) -> None:
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(self._client.close())
            else:
                loop.run_until_complete(self._client.close())
        except RuntimeError:  
            pass

    @greenback.autoawait
    async def _api_call(
        self,
        url: str,
        *,
        method: str = "POST",
        data: Optional[dict] = None,
        json: Optional[dict] = None,
        stream: bool = False,
        headers: Optional[dict] = None,
        **kwargs,
    ) -> Tuple[int, Union[str, ClientResponse], Any]:
        """
        Makes a request to the API, and returns response as status code,
        content and JSON object.
        """
        if data is not None and json is not None:
            raise ValueError("cannot accept both json and data")

        if data is None:
            data = {}
        url = urllib.parse.urljoin(self._server_url, url)

        util.log_info("Request to DeepL API", method=method, url=url)
        util.log_debug("Request details", data=data, json=json)

        if headers is None:
            headers = dict()
        headers.update(
            {k: v for k, v in self.headers.items() if k not in headers}
        )

        status_code, content = await self._client.request_with_backoff(
            method,
            url,
            data=data,
            json=json,
            stream=stream,
            headers=headers,
            **kwargs,
        )
        util.log_info("DeepL API response", url=url, status_code=status_code)

        json = None
        if isinstance(content, str):
            try:
                json = json_module.loads(content)
            except json_module.JSONDecodeError:
                pass
            util.log_debug("Response details", content=content)

        return status_code, content, json

    def _raise_for_status(
        self,
        status_code: int,
        content: Union[str, ClientResponse],
        json: Any,
        glossary: bool = False,
        downloading_document: bool = False,
    ) -> None:
        if not isinstance(content, str):
            content = greenback.await_(content.text())
        return super()._raise_for_status(
            status_code, content, json, glossary, downloading_document
        )

    async def close(self) -> None:
        await self._client.close()
    
    @greenback.autoawait
    async def translate_document_download(
        self,
        handle: DocumentHandle,
        output_file: Union[BinaryIO, Any, None] = None,
        chunk_size: int = 1,
    ) -> Optional[ClientResponse]:
        """Downloads the translated document for the request associated with
        given handle and returns a response object for streaming the data. Call
        iter_content() on the response object to read streamed file data.
        Alternatively, a file-like object may be given as output_file where the
        complete file will be downloaded and written to.

        :param handle: DocumentHandle associated with request.
        :param output_file: (Optional) File-like object to store downloaded
            document. If not provided, use iter_content() on the returned
            response object to read streamed file data.
        :param chunk_size: (Optional) Size of chunk in bytes for streaming.
            Only used if output_file is specified.
        :return: None if output_file is specified, otherwise the
            requests.Response will be returned.
        """

        data = {"document_key": handle.document_key}
        url = f"v2/document/{handle.document_id}/result"

        status_code, response, json = self._api_call(
            url, json=data, stream=True
        )
        # TODO: once we drop py3.6 support, replace this with @overload
        # annotations in `_api_call` and chained private functions.
        # See for example https://stackoverflow.com/a/74070166/4926599
        # In addition, drop the type: ignore annotation on the
        # `import requests` / `from requests`
        assert isinstance(response, ClientResponse)

        self._raise_for_status(
            status_code, "<file>", json, downloading_document=True
        )

        if output_file:
            chunks = response.content.iter_chunked(chunk_size)
            async for chunk in chunks:
                output_file.write(chunk)
            return None
        else:
            return response
    
    async def __aenter__(self) -> Self:
        await greenback.ensure_portal()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()
