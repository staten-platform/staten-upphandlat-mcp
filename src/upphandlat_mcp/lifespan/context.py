import base64
import logging
import threading
from contextlib import asynccontextmanager
from io import BytesIO
from pathlib import Path
from typing import AsyncIterator, TypedDict
from urllib.parse import unquote, urlparse

import httpx
import polars as pl
import yaml
from mcp.server.fastmcp import FastMCP
from statens_mima import MCPSharedCache, create_cache
from upphandlat_mcp.core.config import CsvSourcesConfig, Settings
from upphandlat_mcp.core.config import settings as app_settings

logger = logging.getLogger(__name__)

_global_lifespan_data_cache: "LifespanContext | None" = None
_initialization_lock = threading.Lock()
_initialized_successfully = False


class LifespanContext(TypedDict):
    shared_cache: MCPSharedCache
    available_dataframe_names: list[str]
    settings: Settings
    csv_sources_config: CsvSourcesConfig
    server_name: str


async def get_or_reload_dataframe(
    lifespan_ctx: LifespanContext,
    dataframe_name: str,
) -> pl.DataFrame | None:
    """
    Get a dataframe from cache, or reload it if not found.

    Args:
        lifespan_ctx: The lifespan context containing cache and config
        dataframe_name: Name of the dataframe to retrieve

    Returns:
        The dataframe if found/loaded successfully, None otherwise
    """
    shared_cache = lifespan_ctx["shared_cache"]
    server_name = lifespan_ctx["server_name"]

    # First try to get from cache
    df = await shared_cache.get_dataframe(
        tool_name="datasource",
        server_name=server_name,
        params={"source_name": dataframe_name},
    )

    if df is not None:
        return df

    # If not in cache, try to reload from config
    csv_sources_config = lifespan_ctx["csv_sources_config"]
    source = None

    for src in csv_sources_config.sources:
        if src.name == dataframe_name:
            source = src
            break

    if source is None:
        logger.warning(f"No configuration found for dataframe '{dataframe_name}'")
        return None

    try:
        # Reload the dataframe using the same logic as in app_lifespan
        read_options = source.read_csv_options.to_polars_args()
        logger.info(f"Reloading dataframe '{dataframe_name}' from source")

        url_string = source.url
        parsed_url = urlparse(url_string)
        source_to_read: str | Path | BytesIO

        if parsed_url.scheme in ("http", "https"):
            # Use httpx for robust downloading
            async with httpx.AsyncClient() as client:
                logger.info(f"Downloading data for '{source.name}' from {url_string}")
                # Use a generous timeout for large government data files
                response = await client.get(url_string, timeout=120.0)
                response.raise_for_status()  # Ensure the download was successful
                source_to_read = BytesIO(response.content)
                logger.info(
                    f"Download complete for '{source.name}', size: {len(response.content)} bytes."
                )
        elif parsed_url.scheme == "file":
            file_path_str = parsed_url.path
            source_to_read = Path(unquote(file_path_str))
        elif parsed_url.scheme == "data":
            uri_path_content = parsed_url.path
            try:
                media_type_and_encoding, actual_data_encoded = uri_path_content.split(
                    ",", 1
                )
            except ValueError:
                raise ValueError(f"Invalid data URI format for source '{source.name}'")

            if "base64" in media_type_and_encoding.lower():
                decoded_bytes = base64.b64decode(actual_data_encoded)
                source_to_read = BytesIO(decoded_bytes)
            else:
                decoded_text_data = unquote(actual_data_encoded)
                source_to_read = BytesIO(decoded_text_data.encode("utf-8"))
        else:
            source_to_read = url_string

        df = pl.read_csv(source_to_read, **read_options)

        # Store back in cache
        await shared_cache.put_dataframe(
            df=df,
            tool_name="datasource",
            server_name=server_name,
            params={"source_name": source.name},
            metadata={
                "description": source.description or "",
                "url": source.url,
            },
        )

        logger.info(f"Successfully reloaded and cached dataframe '{dataframe_name}'")
        return df

    except Exception as e:
        logger.error(
            f"Failed to reload dataframe '{dataframe_name}': {e}", exc_info=True
        )
        return None


@asynccontextmanager
async def app_lifespan(server: FastMCP) -> AsyncIterator[LifespanContext]:
    global _global_lifespan_data_cache
    global _initialized_successfully

    if not _initialized_successfully:
        with _initialization_lock:
            if not _initialized_successfully:
                current_csv_sources_config: CsvSourcesConfig
                current_available_dataframe_names: list[str] = []

                try:
                    config_path = app_settings.CSV_SOURCES_CONFIG_PATH.resolve()
                    if not config_path.exists():
                        raise FileNotFoundError(
                            f"CSV sources config not found: {config_path}"
                        )

                    with open(config_path, "r") as f:
                        raw_config = yaml.safe_load(f)
                    current_csv_sources_config = CsvSourcesConfig(**raw_config)

                    # Initialize Statens Mima cache with explicit Redis URL
                    shared_cache_instance = create_cache(
                        redis_url=app_settings.MIMA_REDIS_URL,
                        key_prefix=f"mcp_{server.name}",
                    )
                    health = await shared_cache_instance.health_check()
                    if health.status != "healthy":
                        raise RuntimeError(
                            f"Statens Mima Cache unhealthy: {health.error}"
                        )

                    # Use a single async client for all downloads
                    async with httpx.AsyncClient() as client:
                        for source in current_csv_sources_config.sources:
                            try:
                                read_options = source.read_csv_options.to_polars_args()
                                url_string = source.url
                                parsed_url = urlparse(url_string)
                                source_to_read: str | Path | BytesIO

                                if parsed_url.scheme in ("http", "https"):
                                    logger.info(
                                        f"Downloading data for '{source.name}' from {url_string}"
                                    )
                                    response = await client.get(
                                        url_string, timeout=120.0
                                    )
                                    response.raise_for_status()
                                    source_to_read = BytesIO(response.content)
                                    logger.info(
                                        f"Download complete for '{source.name}', size: {len(response.content)} bytes."
                                    )
                                elif parsed_url.scheme == "file":
                                    file_path_str = parsed_url.path
                                    source_to_read = Path(unquote(file_path_str))
                                elif parsed_url.scheme == "data":
                                    uri_path_content = parsed_url.path
                                    try:
                                        media_type, data_encoded = (
                                            uri_path_content.split(",", 1)
                                        )
                                    except ValueError:
                                        raise ValueError(
                                            f"Invalid data URI for source '{source.name}'"
                                        )

                                    if "base64" in media_type.lower():
                                        source_to_read = BytesIO(
                                            base64.b64decode(data_encoded)
                                        )
                                    else:
                                        source_to_read = BytesIO(
                                            unquote(data_encoded).encode("utf-8")
                                        )
                                else:
                                    source_to_read = url_string

                                df = pl.read_csv(source_to_read, **read_options)
                                # Store DataFrame in Statens Mima cache
                                await shared_cache_instance.put_dataframe(
                                    df=df,
                                    tool_name="datasource",
                                    server_name=server.name,
                                    params={"source_name": source.name},
                                    metadata={
                                        "description": source.description or "",
                                        "url": source.url,
                                    },
                                )
                                current_available_dataframe_names.append(source.name)

                            except Exception as e_read:
                                logger.error(
                                    f"Failed to read or download source '{source.name}'",
                                    exc_info=True,
                                )

                    _global_lifespan_data_cache = {
                        "shared_cache": shared_cache_instance,
                        "available_dataframe_names": current_available_dataframe_names,
                        "settings": app_settings,
                        "csv_sources_config": current_csv_sources_config,
                        "server_name": server.name,
                    }
                    _initialized_successfully = True

                except (FileNotFoundError, yaml.YAMLError, ValueError) as e_config:
                    logger.critical(
                        f"Lifespan critical error during configuration: {e_config}",
                        exc_info=True,
                    )
                    _initialized_successfully = False
                    _global_lifespan_data_cache = None
                    raise
                except Exception as e_outer:
                    logger.critical(
                        f"An unexpected critical error occurred during lifespan setup: {e_outer}",
                        exc_info=True,
                    )
                    _initialized_successfully = False
                    _global_lifespan_data_cache = None
                    raise

    if not _initialized_successfully or _global_lifespan_data_cache is None:
        raise RuntimeError("Lifespan data unavailable due to initialization failure.")

    yield _global_lifespan_data_cache
