"""Cliente HTTP para la API de NASA ADS.

Resuelve tres cosas que de otro modo contaminarian el resto del codigo:

* **Paginacion.** ADS devuelve a lo mucho 2000 filas por llamada; para recorrer
  un resultado completo se usa ``cursorMark``.
* **Rate limits.** La cuota es diaria y se reinicia a medianoche UTC. El cliente
  lee los encabezados ``X-RateLimit-*`` y avisa antes de agotarla.
* **Cache en disco.** Una query identica no se vuelve a pedir. Es lo que hace
  viable iterar sobre la transformacion sin quemar la cuota.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterator, List, Optional

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from astroca.ads.queries import SearchQuery

logger = logging.getLogger(__name__)

BASE_URL = "https://api.adsabs.harvard.edu/v1"


class ADSError(RuntimeError):
    """Fallo al hablar con la API de ADS."""


class ADSRetryableError(ADSError):
    """Fallo transitorio: vale la pena reintentar."""


@dataclass
class RateLimit:
    """Estado de la cuota, leido de los encabezados de la respuesta."""

    limit: Optional[int] = None
    remaining: Optional[int] = None
    reset: Optional[int] = None

    @classmethod
    def from_headers(cls, headers) -> "RateLimit":
        def entero(clave: str) -> Optional[int]:
            valor = headers.get(clave)
            return int(valor) if valor is not None and str(valor).isdigit() else None

        return cls(
            limit=entero("X-RateLimit-Limit"),
            remaining=entero("X-RateLimit-Remaining"),
            reset=entero("X-RateLimit-Reset"),
        )

    @property
    def reset_at(self) -> Optional[str]:
        if self.reset is None:
            return None
        return time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(self.reset))

    def __str__(self) -> str:
        if self.limit is None:
            return "cuota desconocida"
        return f"{self.remaining}/{self.limit} llamadas restantes (se reinicia {self.reset_at})"


class ResponseCache:
    """Cache de respuestas en disco, una carpeta por query."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def _ruta(self, key: str) -> Path:
        return self.root / f"{key}.json"

    def get(self, key: str) -> Optional[List[dict]]:
        ruta = self._ruta(key)
        if not ruta.exists():
            return None
        try:
            with ruta.open(encoding="utf-8") as fh:
                return json.load(fh)
        except (json.JSONDecodeError, OSError):
            logger.warning("Cache corrupta en %s, la ignoro", ruta)
            return None

    def set(self, key: str, docs: List[dict]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        with self._ruta(key).open("w", encoding="utf-8") as fh:
            json.dump(docs, fh)


class ADSClient:
    """Cliente de la API de ADS con cache, reintentos y control de cuota."""

    def __init__(
        self,
        token: str,
        cache: Optional[ResponseCache] = None,
        request_delay: float = 0.5,
        session: Optional[requests.Session] = None,
    ) -> None:
        self._token = token
        self._cache = cache
        self._request_delay = request_delay
        self._session = session or requests.Session()
        self._session.headers.update(
            {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        )
        self.rate_limit = RateLimit()

    # -- API publica -------------------------------------------------------- #
    def search(self, query: SearchQuery, use_cache: bool = True) -> List[dict]:
        """Devuelve todos los documentos que cumplen ``query``.

        Recorre la paginacion completa. Si hay cache y ``use_cache``, no toca
        la red.
        """
        etiqueta = query.label or "query"

        if use_cache and self._cache is not None:
            en_cache = self._cache.get(query.cache_key)
            if en_cache is not None:
                logger.info("[%s] CACHE HIT (%s): %d docs, no se llama a la API",
                            etiqueta, query.cache_key, len(en_cache))
                return en_cache
            logger.info("[%s] CACHE MISS (%s): se descarga de la API",
                        etiqueta, query.cache_key)

        logger.debug("[%s] q = %s", etiqueta, query.q)
        inicio = time.monotonic()
        docs = list(self._paginate(query))
        transcurrido = time.monotonic() - inicio

        velocidad = len(docs) / transcurrido if transcurrido > 0 else 0.0
        logger.info("[%s] descarga completa: %d docs en %.1fs (%.0f docs/s)",
                    etiqueta, len(docs), transcurrido, velocidad)

        if self._cache is not None:
            self._cache.set(query.cache_key, docs)
            logger.debug("[%s] guardado en cache: %s", etiqueta, query.cache_key)

        return docs

    def count(self, query: SearchQuery) -> int:
        """Numero de resultados sin descargarlos todos."""
        params = query.as_params()
        params["rows"] = 0
        respuesta = self._get("/search/query", params)
        return int(respuesta["response"]["numFound"])

    def metrics(self, bibcodes: List[str]) -> dict:
        """Metricas agregadas (citas, indice h) para un conjunto de bibcodes."""
        if not bibcodes:
            return {}
        return self._post("/metrics", {"bibcodes": bibcodes})

    # -- interna ------------------------------------------------------------ #
    def _paginate(self, query: SearchQuery) -> Iterator[dict]:
        """Recorre los resultados con ``cursorMark``."""
        etiqueta = query.label or "query"
        cursor = "*"
        obtenidos = 0
        pagina = 0
        total: Optional[int] = None

        while True:
            params = query.as_params()
            params["cursorMark"] = cursor
            pagina += 1

            respuesta = self._get("/search/query", params)
            bloque = respuesta["response"]
            docs = bloque.get("docs", [])

            if total is None:
                total = int(bloque.get("numFound", 0))
                paginas = -(-total // query.rows) if query.rows else 1
                logger.info("[%s] %d resultados en ADS (~%d paginas de %d)",
                            etiqueta, total, paginas, query.rows)
                if total == 0:
                    logger.warning("[%s] la busqueda no devolvio resultados", etiqueta)

            for doc in docs:
                yield doc
                obtenidos += 1
                if query.max_records is not None and obtenidos >= query.max_records:
                    logger.info("[%s] corte en max_records=%d", etiqueta, query.max_records)
                    return

            porcentaje = (obtenidos / total * 100) if total else 100.0
            logger.info("[%s]   pagina %d: +%d docs | %d/%d (%.1f%%) | %s",
                        etiqueta, pagina, len(docs), obtenidos, total, porcentaje,
                        self.rate_limit)

            siguiente = respuesta.get("nextCursorMark")
            # ADS repite el cursor cuando ya no hay mas paginas.
            if not docs or siguiente is None or siguiente == cursor:
                return
            cursor = siguiente

    @retry(
        retry=retry_if_exception_type(ADSRetryableError),
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=2, min=2, max=30),
        reraise=True,
    )
    def _get(self, path: str, params: Dict) -> dict:
        return self._request("GET", path, params=params)

    @retry(
        retry=retry_if_exception_type(ADSRetryableError),
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=2, min=2, max=30),
        reraise=True,
    )
    def _post(self, path: str, payload: Dict) -> dict:
        return self._request("POST", path, json=payload)

    def _request(self, method: str, path: str, **kwargs) -> dict:
        if self._request_delay:
            time.sleep(self._request_delay)

        logger.debug("%s %s", method, path)

        try:
            respuesta = self._session.request(method, f"{BASE_URL}{path}", timeout=60, **kwargs)
        except requests.RequestException as exc:
            raise ADSRetryableError(f"Error de red hablando con ADS: {exc}") from exc

        self.rate_limit = RateLimit.from_headers(respuesta.headers)
        self._avisar_si_queda_poca_cuota()

        if respuesta.status_code == 429:
            raise ADSError(
                f"Cuota de ADS agotada. {self.rate_limit}. "
                "Los datos ya descargados quedan en cache: al reiniciarse la cuota, "
                "`make extract` retoma donde quedo."
            )
        if respuesta.status_code in (500, 502, 503, 504):
            logger.warning("ADS respondio %d, se reintenta con backoff", respuesta.status_code)
            raise ADSRetryableError(f"ADS respondio {respuesta.status_code}, reintentando")
        if respuesta.status_code == 401:
            raise ADSError("ADS rechazo el token (401). Revisa ADS_DEV_KEY en .env")
        if not respuesta.ok:
            raise ADSError(f"ADS respondio {respuesta.status_code}: {respuesta.text[:300]}")

        try:
            return respuesta.json()
        except ValueError as exc:
            raise ADSError("ADS devolvio una respuesta que no es JSON") from exc

    def _avisar_si_queda_poca_cuota(self) -> None:
        restantes = self.rate_limit.remaining
        if restantes is not None and restantes < 50:
            logger.warning("Queda poca cuota de ADS: %s", self.rate_limit)
