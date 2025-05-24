import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator, TypedDict
from urllib.parse import unquote, urlparse

import polars as pl
import yaml
from mcp.server.fastmcp import FastMCP
from upphandlat_mcp.core.config import CsvSourcesConfig, Settings
from upphandlat_mcp.core.config import settings as app_settings

logger = logging.getLogger(__name__)


class LifespanContext(TypedDict):
    dataframes: dict[str, pl.DataFrame]
    settings: Settings
    csv_sources_config: CsvSourcesConfig


@asynccontextmanager
async def app_lifespan(server: FastMCP) -> AsyncIterator[LifespanContext]:
    print("LIFESPAN_TRACE: app_lifespan started.", file=sys.stderr, flush=True)
    loaded_dataframes: dict[str, pl.DataFrame] = {}

    try:
        print("LIFESPAN_TRACE: Resolving CSV_SOURCES_CONFIG_PATH.", file=sys.stderr, flush=True)
        config_path = app_settings.CSV_SOURCES_CONFIG_PATH.resolve()
        print(f"LIFESPAN_TRACE: Config path resolved to: {config_path}", file=sys.stderr, flush=True)

        if not config_path.exists():
            print(f"LIFESPAN_ERROR_STDERR: CSV sources configuration file not found at {config_path}", file=sys.stderr, flush=True)
            raise FileNotFoundError(f"CSV sources config not found: {config_path}")

        print(f"LIFESPAN_TRACE: Opening config file: {config_path}", file=sys.stderr, flush=True)
        with open(config_path, "r") as f:
            print("LIFESPAN_TRACE: Reading config file content.", file=sys.stderr, flush=True)
            raw_config = yaml.safe_load(f)
        print("LIFESPAN_TRACE: Config file loaded and parsed by YAML.", file=sys.stderr, flush=True)

        csv_sources_config = CsvSourcesConfig(**raw_config)
        print("LIFESPAN_TRACE: CsvSourcesConfig model validated.", file=sys.stderr, flush=True)

        if not csv_sources_config.sources:
            print(f"LIFESPAN_TRACE_WARNING: No CSV sources defined in {config_path}. Server will start with no data.", file=sys.stderr, flush=True)

        for source in csv_sources_config.sources:
            print(f"LIFESPAN_TRACE: Processing source '{source.name}', URL: {source.url}", file=sys.stderr, flush=True)
            try:
                read_options = source.read_csv_options.to_polars_args()
                logger.debug(
                    f"Polars read_csv options for '{source.name}': {read_options}"
                )

                # source.url is a string, potentially a file URI or HTTP/HTTPS URL
                print(f"LIFESPAN_TRACE: Parsing URL for source '{source.name}': {source.url}", file=sys.stderr, flush=True)
                url_string = source.url
                parsed_url = urlparse(url_string)
                source_to_read: str | Path

                if parsed_url.scheme == "file":
                    # Convert file URI to a Path object for Polars
                    file_path_str = parsed_url.path
                    # On Windows, urlparse on "file:///C:/path" gives path "/C:/path"
                    # Path() needs "C:/path"
                    if sys.platform == "win32" and file_path_str.startswith("/") and len(file_path_str) > 1 and file_path_str[1] == ":":
                        file_path_str = file_path_str[1:]
                    
                    source_to_read = Path(unquote(file_path_str)) # unquote handles e.g. %20
                    print(f"LIFESPAN_TRACE: Reading local file for source '{source.name}': {source_to_read}", file=sys.stderr, flush=True)
                else:
                    source_to_read = url_string # Use the original string for http, https etc.
                    print(f"LIFESPAN_TRACE: Reading remote URL for source '{source.name}': {source_to_read}", file=sys.stderr, flush=True)
                
                print(f"LIFESPAN_TRACE: Calling pl.read_csv for source '{source.name}' with source: {source_to_read}", file=sys.stderr, flush=True)
                df = pl.read_csv(source_to_read, **read_options)
                print(f"LIFESPAN_TRACE: pl.read_csv completed for source '{source.name}'. Shape: {df.shape}", file=sys.stderr, flush=True)

                loaded_dataframes[source.name] = df
            except Exception as e_read:
                print(f"LIFESPAN_ERROR_STDERR: Failed to load/parse CSV for '{source.name}' from {source.url}: {e_read}", file=sys.stderr, flush=True)
                # Log exc_info to main logger as well for full traceback if needed
                logger.error(f"Exception details for source '{source.name}'", exc_info=True)

        print("LIFESPAN_TRACE: Finished loading all sources.", file=sys.stderr, flush=True)
        if not loaded_dataframes:
            print("LIFESPAN_TRACE_WARNING: No DataFrames were loaded successfully. Server will operate without data.", file=sys.stderr, flush=True)

        context_data: LifespanContext = {
            "dataframes": loaded_dataframes,
            "settings": app_settings,
            "csv_sources_config": csv_sources_config,
        }
        yield context_data
        print("LIFESPAN_TRACE: app_lifespan context manager is being exited.", file=sys.stderr, flush=True)

    except FileNotFoundError as e_fnf:
        logger.critical(f"Lifespan critical error (FileNotFound): {e_fnf}")
        print(
            f"LIFESPAN_ERROR_STDERR: FileNotFoundError: {e_fnf}", file=sys.stderr, flush=True
        )
        raise
    except (
        yaml.YAMLError,
        ValueError,
    ) as e_yaml_parse:
        logger.critical(
            f"Lifespan critical error parsing YAML config or validating sources: {e_yaml_parse}",
            exc_info=True,
        )
        print(
            f"LIFESPAN_ERROR_STDERR: YAML/ValueError: {e_yaml_parse}", file=sys.stderr, flush=True
        )
        raise
    except Exception as e_outer:
        logger.critical(
            f"Lifespan critical error during data loading: {e_outer}", exc_info=True
        )
        print(
            f"LIFESPAN_ERROR_STDERR: Generic Exception: {e_outer}", file=sys.stderr, flush=True
        )
        raise
    finally:
        print("LIFESPAN_TRACE: app_lifespan finally block.", file=sys.stderr, flush=True)
