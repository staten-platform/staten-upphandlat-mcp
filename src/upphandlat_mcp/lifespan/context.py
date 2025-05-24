import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator, TypedDict

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
    logger.info("MCP Server lifespan: Initializing application...")
    loaded_dataframes: dict[str, pl.DataFrame] = {}

    try:
        config_path = app_settings.CSV_SOURCES_CONFIG_PATH.resolve()
        logger.info(f"Attempting to load CSV sources configuration from: {config_path}")
        if not config_path.exists():
            logger.error(f"CSV sources configuration file not found at {config_path}")
            raise FileNotFoundError(f"CSV sources config not found: {config_path}")

        with open(config_path, "r") as f:
            raw_config = yaml.safe_load(f)

        csv_sources_config = CsvSourcesConfig(**raw_config)

        if not csv_sources_config.sources:
            logger.warning(
                f"No CSV sources defined in {config_path}. Server will start with no data."
            )

        for source in csv_sources_config.sources:
            logger.info(
                f"Loading data for source '{source.name}' from URL: {source.url}"
            )
            try:
                read_options = source.read_csv_options.to_polars_args()
                logger.debug(
                    f"Polars read_csv options for '{source.name}': {read_options}"
                )

                df = pl.read_csv(source.url, **read_options)

                logger.info(
                    f"Successfully loaded CSV for '{source.name}'. Shape: {df.shape}. Columns: {df.columns}"
                )
                loaded_dataframes[source.name] = df
            except Exception as e_read:
                logger.error(
                    f"Failed to load or parse CSV for source '{source.name}' from {source.url}: {e_read}",
                    exc_info=True,
                )

        if not loaded_dataframes:
            logger.warning(
                "No DataFrames were loaded successfully. Server will operate without data."
            )

        context_data: LifespanContext = {
            "dataframes": loaded_dataframes,
            "settings": app_settings,
            "csv_sources_config": csv_sources_config,
        }
        yield context_data

    except FileNotFoundError as e_fnf:
        logger.critical(f"Lifespan critical error (FileNotFound): {e_fnf}")
        raise
    except (
        yaml.YAMLError,
        ValueError,
    ) as e_yaml_parse:
        logger.critical(
            f"Lifespan critical error parsing YAML config or validating sources: {e_yaml_parse}",
            exc_info=True,
        )
        raise
    except Exception as e_outer:
        logger.critical(
            f"Lifespan critical error during data loading: {e_outer}", exc_info=True
        )
        raise
    finally:
        logger.info("MCP Server lifespan: Application shutdown.")
