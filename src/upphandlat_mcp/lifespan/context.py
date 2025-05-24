import base64
import logging
import sys
from contextlib import asynccontextmanager
from io import BytesIO
from pathlib import Path
from typing import AsyncIterator, TypedDict
from urllib.parse import unquote, urlparse
import threading # Added for lock

import polars as pl
import yaml
from mcp.server.fastmcp import FastMCP
from upphandlat_mcp.core.config import CsvSourcesConfig, Settings
from upphandlat_mcp.core.config import settings as app_settings

logger = logging.getLogger(__name__)

# Global store for lifespan data to ensure one-time initialization
_global_lifespan_data_cache: 'LifespanContext | None' = None
_initialization_lock = threading.Lock()
_initialized_successfully = False # Flag to track successful initialization

class LifespanContext(TypedDict):
    dataframes: dict[str, pl.DataFrame]
    settings: Settings
    csv_sources_config: CsvSourcesConfig


@asynccontextmanager
async def app_lifespan(server: FastMCP) -> AsyncIterator[LifespanContext]:
    global _global_lifespan_data_cache
    global _initialized_successfully

    print("LIFESPAN_TRACE: app_lifespan entry.", file=sys.stderr, flush=True)

    if not _initialized_successfully: # Check first without lock for minor optimization
        with _initialization_lock: # Ensure only one thread/task performs initialization
            if not _initialized_successfully: # Double-check after acquiring lock
                print("LIFESPAN_TRACE: Performing one-time initialization.", file=sys.stderr, flush=True)
                
                current_loaded_dataframes: dict[str, pl.DataFrame] = {}
                # This variable will be populated within the try block
                # It needs to be accessible for the _global_lifespan_data_cache assignment
                # Initialize to a default that indicates it hasn't been set, or handle potential None
                current_csv_sources_config: CsvSourcesConfig

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
                    
                    current_csv_sources_config = CsvSourcesConfig(**raw_config) # Assign here
                    print("LIFESPAN_TRACE: CsvSourcesConfig model validated.", file=sys.stderr, flush=True)

                    if not current_csv_sources_config.sources:
                        print(f"LIFESPAN_TRACE_WARNING: No CSV sources defined in {config_path}. Server will start with no data.", file=sys.stderr, flush=True)

                    for source in current_csv_sources_config.sources:
                        print(f"LIFESPAN_TRACE: Processing source '{source.name}', URL: {source.url}", file=sys.stderr, flush=True)
                        try:
                            read_options = source.read_csv_options.to_polars_args()
                            logger.debug(f"Polars read_csv options for '{source.name}': {read_options}")

                            url_string = source.url
                            parsed_url = urlparse(url_string)
                            source_to_read: str | Path | BytesIO

                            if parsed_url.scheme == "file":
                                file_path_str = parsed_url.path
                                if sys.platform == "win32" and file_path_str.startswith("/") and len(file_path_str) > 1 and file_path_str[1] == ":":
                                    file_path_str = file_path_str[1:]
                                source_to_read = Path(unquote(file_path_str))
                                print(f"LIFESPAN_TRACE: Reading local file for source '{source.name}': {source_to_read}", file=sys.stderr, flush=True)
                            elif parsed_url.scheme == "data":
                                print(f"LIFESPAN_TRACE: Processing data URI for source '{source.name}'", file=sys.stderr, flush=True)
                                uri_path_content = parsed_url.path
                                try:
                                    media_type_and_encoding, actual_data_encoded = uri_path_content.split(',', 1)
                                except ValueError:
                                    print(f"LIFESPAN_ERROR_STDERR: Invalid data URI format for source '{source.name}': missing comma separator in '{uri_path_content}'", file=sys.stderr, flush=True)
                                    raise ValueError(f"Invalid data URI format for source '{source.name}'")

                                if "base64" in media_type_and_encoding.lower():
                                    print(f"LIFESPAN_TRACE: Decoding base64 data for source '{source.name}'", file=sys.stderr, flush=True)
                                    decoded_bytes = base64.b64decode(actual_data_encoded)
                                    source_to_read = BytesIO(decoded_bytes)
                                    print(f"LIFESPAN_TRACE: Base64 data prepared as BytesIO for source '{source.name}'", file=sys.stderr, flush=True)
                                else:
                                    print(f"LIFESPAN_TRACE: URL-decoding plain text data for source '{source.name}'", file=sys.stderr, flush=True)
                                    decoded_text_data = unquote(actual_data_encoded)
                                    source_to_read = BytesIO(decoded_text_data.encode('utf-8'))
                                    print(f"LIFESPAN_TRACE: Plain text data prepared as BytesIO for source '{source.name}'", file=sys.stderr, flush=True)
                                
                                preview_data_str = "<BytesIO data>"
                                print(f"LIFESPAN_TRACE: Prepared data for Polars from data URI for '{source.name}', preview: {preview_data_str}", file=sys.stderr, flush=True)
                            else: 
                                source_to_read = url_string
                                print(f"LIFESPAN_TRACE: Reading remote URL for source '{source.name}': {source_to_read}", file=sys.stderr, flush=True)
                            
                            print(f"LIFESPAN_TRACE: Calling pl.read_csv for source '{source.name}' with source type: {type(source_to_read)}", file=sys.stderr, flush=True)
                            df = pl.read_csv(source_to_read, **read_options)
                            print(f"LIFESPAN_TRACE: pl.read_csv completed for source '{source.name}'. Shape: {df.shape}", file=sys.stderr, flush=True)
                            current_loaded_dataframes[source.name] = df
                        except Exception as e_read:
                            print(f"LIFESPAN_ERROR_STDERR: Failed to load/parse CSV for '{source.name}' from {source.url}: {e_read}", file=sys.stderr, flush=True)
                            logger.error(f"Exception details for source '{source.name}'", exc_info=True)

                    print("LIFESPAN_TRACE: Finished loading all sources.", file=sys.stderr, flush=True)
                    if not current_loaded_dataframes:
                        print("LIFESPAN_TRACE_WARNING: No DataFrames were loaded successfully. Server will operate without data.", file=sys.stderr, flush=True)

                    _global_lifespan_data_cache = {
                        "dataframes": current_loaded_dataframes,
                        "settings": app_settings,
                        "csv_sources_config": current_csv_sources_config,
                    }
                    _initialized_successfully = True
                    print("LIFESPAN_TRACE: One-time initialization complete. Data cached.", file=sys.stderr, flush=True)

                except FileNotFoundError as e_fnf:
                    logger.critical(f"Lifespan critical error (FileNotFound): {e_fnf}")
                    print(f"LIFESPAN_ERROR_STDERR: FileNotFoundError: {e_fnf}", file=sys.stderr, flush=True)
                    _initialized_successfully = False
                    _global_lifespan_data_cache = None
                    raise
                except (yaml.YAMLError, ValueError) as e_yaml_parse:
                    logger.critical(f"Lifespan critical error parsing YAML config or validating sources: {e_yaml_parse}", exc_info=True)
                    print(f"LIFESPAN_ERROR_STDERR: YAML/ValueError: {e_yaml_parse}", file=sys.stderr, flush=True)
                    _initialized_successfully = False
                    _global_lifespan_data_cache = None
                    raise
                except Exception as e_outer: # Catch any other error during initialization
                    logger.critical(f"Lifespan critical error during data loading: {e_outer}", exc_info=True)
                    print(f"LIFESPAN_ERROR_STDERR: Generic Exception during init: {e_outer}", file=sys.stderr, flush=True)
                    _initialized_successfully = False
                    _global_lifespan_data_cache = None
                    raise
            else: # Another thread/task initialized it while this one was waiting for the lock
                print("LIFESPAN_TRACE: Initialization already performed by another concurrent call, using cached data.", file=sys.stderr, flush=True)
    else:
        print("LIFESPAN_TRACE: Already initialized, using cached data.", file=sys.stderr, flush=True)

    if not _initialized_successfully or _global_lifespan_data_cache is None:
        # This state indicates a failure during the one-time initialization.
        print("LIFESPAN_ERROR_STDERR: Lifespan data is not available. Initialization likely failed.", file=sys.stderr, flush=True)
        raise RuntimeError("Lifespan data unavailable due to initialization failure.")

    try:
        yield _global_lifespan_data_cache
        print("LIFESPAN_TRACE: app_lifespan context yielded.", file=sys.stderr, flush=True)
    finally:
        # For this global cache pattern, the "finally" of an individual lifespan call
        # should not clear the global cache. Global cleanup would be process-level.
        print("LIFESPAN_TRACE: app_lifespan finally block (individual call). Global cache remains.", file=sys.stderr, flush=True)
