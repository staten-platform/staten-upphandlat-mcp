import logging
import sys

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # dotenv is optional, continue without it if not installed
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stderr,
)

logger = logging.getLogger(__name__)


def main() -> None:
    """
    Main entry point for the upphandlat-mcp command-line interface.
    This function initializes and runs the MCP server.
    """
    logger.info("Executing upphandlat-mcp CLI entry point...")
    try:
        from upphandlat_mcp.server import run_mcp

        run_mcp()
        logger.info("upphandlat-mcp CLI execution finished successfully.")

    except ImportError as e:
        logger.critical(f"Failed to import server components: {e}", exc_info=True)
        sys.exit(1)

    except Exception as e:
        logger.critical(f"An unexpected error occurred in the CLI: {e}", exc_info=True)
        sys.exit(1)
