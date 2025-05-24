"""
Entry point for executing the upphandlat_mcp package as a module.
(e.g., python -m upphandlat_mcp)
"""

# Ensure that the main function from __init__ is found correctly
# when running as `python -m upphandlat_mcp`.
# The current working directory when running `python -m` from the project root
# will typically be the project root, and `src` should be in PYTHONPATH
# or Python should be able to find `upphandlat_mcp` if it's installed.

if __package__ is None and not hasattr(__builtins__, "__import__"):
    # This block is for older Python versions or specific execution contexts
    # where __package__ might not be set. It attempts to ensure the parent
    # directory of `upphandlat_mcp` (i.e., `src`) is in sys.path.
    # For modern Python and typical execution, this might not be strictly necessary
    # if PYTHONPATH is set correctly or the package is installed.
    import os
    import sys
    from pathlib import Path
    # Assuming __main__.py is in src/upphandlat_mcp/
    # then Path(__file__).resolve().parent is src/upphandlat_mcp
    # Path(__file__).resolve().parent.parent is src
    # Path(__file__).resolve().parent.parent.parent is the project root
    
    # Let's try a simpler approach first, relying on standard module resolution.
    # If issues persist, more complex path manipulation might be needed,
    # but usually `python -m` handles this well if `src` is discoverable.
    pass


from upphandlat_mcp import main

if __name__ == "__main__":
    main()
