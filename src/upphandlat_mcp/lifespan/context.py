import base64
import logging
import threading
from contextlib import asynccontextmanager
from io import BytesIO
from pathlib import Path
from typing import AsyncIterator, TypedDict
from urllib.parse import unquote, urlparse

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

                    # Initialize Statens Mima cache
                    shared_cache_instance = create_cache(
                        key_prefix=f"mcp_{server.name}"
                    )
                    # Verify cache health
                    health = await shared_cache_instance.health_check()
                    if health.status != "healthy":
                        logger.error(f"Statens Mima Cache unhealthy: {health.error}")
                        raise RuntimeError(
                            f"Statens Mima Cache unhealthy: {health.error}"
                        )

                    for source in current_csv_sources_config.sources:
                        try:
                            read_options = source.read_csv_options.to_polars_args()
                            logger.debug(
                                f"Polars read_csv options for '{source.name}': {read_options}"
                            )

                            url_string = source.url
                            parsed_url = urlparse(url_string)
                            source_to_read: str | Path | BytesIO

                            if parsed_url.scheme == "file":
                                file_path_str = parsed_url.path
                                source_to_read = Path(unquote(file_path_str))

                            elif parsed_url.scheme == "data":
                                uri_path_content = parsed_url.path
                                try:
                                    media_type_and_encoding, actual_data_encoded = (
                                        uri_path_content.split(",", 1)
                                    )
                                except ValueError:
                                    raise ValueError(
                                        f"Invalid data URI format for source '{source.name}'"
                                    )

                                if "base64" in media_type_and_encoding.lower():
                                    decoded_bytes = base64.b64decode(
                                        actual_data_encoded
                                    )
                                    source_to_read = BytesIO(decoded_bytes)
                                else:
                                    decoded_text_data = unquote(actual_data_encoded)
                                    source_to_read = BytesIO(
                                        decoded_text_data.encode("utf-8")
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
                                f"Exception details for source '{source.name}'",
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

                except FileNotFoundError as e_fnf:
                    logger.critical(f"Lifespan critical error (FileNotFound): {e_fnf}")
                    _initialized_successfully = False
                    _global_lifespan_data_cache = None
                    raise
                except (yaml.YAMLError, ValueError) as e_yaml_parse:
                    logger.critical(
                        f"Lifespan critical error parsing YAML config or validating sources: {e_yaml_parse}",
                        exc_info=True,
                    )
                    _initialized_successfully = False
                    _global_lifespan_data_cache = None
                    raise
                except Exception as e_outer:
                    logger.critical(
                        f"Lifespan critical error during data loading: {e_outer}",
                        exc_info=True,
                    )
                    _initialized_successfully = False
                    _global_lifespan_data_cache = None
                    raise

    if not _initialized_successfully or _global_lifespan_data_cache is None:
        raise RuntimeError("Lifespan data unavailable due to initialization failure.")

    yield _global_lifespan_data_cache
