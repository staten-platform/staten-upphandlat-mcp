"""
Entry point for executing the upphandlat_mcp package as a module.
(e.g., python -m upphandlat_mcp)
"""

if __package__ is None and not hasattr(__builtins__, "__import__"):
    import os
    import sys
    from pathlib import Path

    pass


from upphandlat_mcp import main

if __name__ == "__main__":
    main()
