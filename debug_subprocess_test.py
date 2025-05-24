import asyncio
import os
import sys
import subprocess
import tempfile
from pathlib import Path

# Ensure the script can find the upphandlat_mcp module, assuming this script is in the project root
PROJECT_ROOT = Path(__file__).resolve().parent
SRC_PATH = PROJECT_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

# --- Test 1: Basic Subprocess ---
print("--- Test 1: Basic subprocess ---")
try:
    process = subprocess.run([sys.executable, "-c", "print('Basic subprocess OK')"], capture_output=True, text=True, timeout=5)
    print(f"Stdout: {process.stdout.strip()}")
    print(f"Stderr: {process.stderr.strip()}")
    print(f"Return code: {process.returncode}")
except subprocess.TimeoutExpired:
    print("Basic subprocess TIMED OUT")
except Exception as e:
    print(f"Basic subprocess FAILED: {e}")
print("-" * 30)

# --- Test 2: Import Test ---
print("--- Test 2: Import test ---")
# This test checks if merely importing the module causes issues.
# It's crucial that upphandlat_mcp can be imported without side effects that hang.
import_test_script = """
import sys
from pathlib import Path
# Calculate PROJECT_ROOT relative to the temporary script's location
# This assumes the temp script is created in a standard temp directory,
# and the original project structure (src/, etc.) is two levels up from where this temp script runs.
# Adjust if tempfile.NamedTemporaryFile places files differently or if project structure is deeper.
# For a script in /tmp/somescript.py, and project at /path/to/project, this needs adjustment.
# Let's assume the temp script is created in PROJECT_ROOT for simplicity of pathing.
# If NamedTemporaryFile(dir=PROJECT_ROOT) is used, then Path(__file__).resolve().parent is PROJECT_ROOT.
# If NamedTemporaryFile uses a system temp dir, this relative path will be wrong.
# The main script sets PYTHONUNBUFFERED and PYTHONPATH for Test 3 and 4,
# let's ensure this import test also has robust module discovery.

# Simplest way: Assume the main script (debug_subprocess_test.py) correctly sets up sys.path
# for the subprocess if needed, or that the module is installed/discoverable.
# For direct execution of a string, it's harder. Let's try to make it robust.

print(f"Initial sys.path in import_test_script: {{sys.path}}")
# The following assumes that the debug_subprocess_test.py is in PROJECT_ROOT
# and SRC_PATH is PROJECT_ROOT / "src".
# This path needs to be valid from the context of the *subprocess*.
# A common way is to pass it via an environment variable or ensure the module is installed.

# Let's try adding a known path if not already present.
# This assumes the debug_subprocess_test.py is run from the project root.
# And that the temp script can infer this. This is tricky.
# A more robust way for the temp script:
# Rely on PYTHONPATH being set by the parent, or the module being installed.
# For now, let's assume PYTHONPATH is inherited or module is in default search paths.

# Path to src, assuming this temp script is run from a context where this relative path makes sense
# This is fragile. A better way is to pass an absolute path or ensure PYTHONPATH.
# For this test, let's assume the module is importable if PYTHONPATH is set correctly by the caller (it is not for this simple subprocess.run)
# Or if the package is installed in the environment.

# Let's try to make the temp script add the src dir from its perspective
# This assumes the temp script is created in the project root.
# If not, this path will be wrong.
# script_dir = Path(__file__).resolve().parent
# src_dir_to_add = script_dir / "src" # if temp script is in project root
# if str(src_dir_to_add) not in sys.path:
#    sys.path.insert(0, str(src_dir_to_add))


try:
    print("Attempting to import upphandlat_mcp...")
    import upphandlat_mcp
    print("Import upphandlat_mcp OK")
except ModuleNotFoundError:
    print("upphandlat_mcp not found. This might be a PYTHONPATH issue for the subprocess.", file=sys.stderr)
    # Attempt to add likely src path if module not found
    # This is a guess, assuming debug_subprocess_test.py is in project root.
    # And that the temp script is also created there.
    # Path to src, assuming this temp script is in the project root.
    current_script_path = Path(__file__).resolve()
    project_root_guess = current_script_path.parent # if temp script is in project root
    src_path_guess = project_root_guess / "src"
    if src_path_guess.exists() and str(src_path_guess) not in sys.path:
        sys.path.insert(0, str(src_path_guess))
        print(f"Added {{src_path_guess}} to sys.path. Retrying import...")
        try:
            import upphandlat_mcp
            print("Import upphandlat_mcp OK after path adjustment.")
        except Exception as e_retry:
            print(f"Import upphandlat_mcp FAILED even after path adjustment: {{e_retry}}", file=sys.stderr)
            sys.exit(1)
    else:
        sys.exit(1) # Exit if module not found and path guess didn't work or apply
except Exception as e:
    print(f"Import upphandlat_mcp FAILED: {{e}}", file=sys.stderr)
    sys.exit(1)
"""
script_path_for_import_test = None
try:
    # Create the temporary script in the project root for simpler path management inside the script
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".py", dir=PROJECT_ROOT) as tmp_script:
        tmp_script.write(import_test_script)
        script_path_for_import_test = tmp_script.name
    
    # Environment for the import test subprocess
    import_env = os.environ.copy()
    import_env["PYTHONPATH"] = str(SRC_PATH) + os.pathsep + import_env.get("PYTHONPATH", "")
    import_env["PYTHONUNBUFFERED"] = "1"

    process = subprocess.run([sys.executable, script_path_for_import_test],
                             capture_output=True, text=True, timeout=10, env=import_env)
    print(f"Stdout:\n{process.stdout.strip()}")
    print(f"Stderr:\n{process.stderr.strip()}")
    print(f"Return code: {process.returncode}")
except subprocess.TimeoutExpired:
    print("Import test TIMED OUT")
except Exception as e:
    print(f"Import test FAILED: {e}")
finally:
    if script_path_for_import_test and os.path.exists(script_path_for_import_test):
        os.remove(script_path_for_import_test)
print("-" * 30)

# --- Test 3: Module Execution Test (Minimal Config) ---
print("--- Test 3: Module execution test (minimal config) ---")
# This test runs `python -m upphandlat_mcp` with a minimal config and stdio transport.
# It checks if the server starts up enough to print its initial logs or hangs.
# It also checks if the MCP_SUBPROCESS_LOGFILE is created.

minimal_config_content = """
toolbox_title: "Minimal Test"
toolbox_description: "Minimal Test Description"
sources:
  - name: "minimal_source"
    url: "data:text/csv,header1,header2%0Avalue1,value2"
    description: "A minimal inline CSV."
    read_csv_options:
      separator: ","
"""
debug_log_file = PROJECT_ROOT / "debug_module_exec.log"
if debug_log_file.exists():
    debug_log_file.unlink()

config_file_path_module_exec = None
try:
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".yaml", dir=PROJECT_ROOT) as tmp_config_file:
        tmp_config_file.write(minimal_config_content)
        config_file_path_module_exec = Path(tmp_config_file.name)

    env = os.environ.copy()
    env["CSV_SOURCES_CONFIG_PATH"] = str(config_file_path_module_exec)
    env["MCP_TRANSPORT"] = "stdio" # Force stdio for this test
    env["MCP_SUBPROCESS_LOGFILE"] = str(debug_log_file) # For checking log output
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONPATH"] = str(SRC_PATH) + os.pathsep + env.get("PYTHONPATH", "")


    print(f"Using config: {config_file_path_module_exec}")
    print(f"Expecting log at: {debug_log_file}")
    print(f"PYTHONPATH: {env['PYTHONPATH']}")

    process = subprocess.Popen([sys.executable, "-m", "upphandlat_mcp"],
                               env=env,
                               stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE,
                               text=True,
                               cwd=PROJECT_ROOT) # Ensure CWD is project root
    try:
        stdout, stderr = process.communicate(timeout=15) 
        print(f"Module execution Stdout:\n{stdout.strip()}")
        print(f"Module execution Stderr:\n{stderr.strip()}")
        print(f"Module execution Return code: {process.returncode}")
    except subprocess.TimeoutExpired:
        print("Module execution TIMED OUT")
        process.kill()
        stdout, stderr = process.communicate()
        print(f"Module execution Stdout (after kill):\n{stdout.strip()}")
        print(f"Module execution Stderr (after kill):\n{stderr.strip()}")

    if debug_log_file.exists():
        print(f"Contents of {debug_log_file}:")
        try:
            print(debug_log_file.read_text())
        except Exception as e_read:
            print(f"Error reading log file: {e_read}")
    else:
        print(f"{debug_log_file} was NOT created.")

except Exception as e:
    print(f"Module execution test FAILED: {e}")
    import traceback
    traceback.print_exc()
finally:
    if config_file_path_module_exec and config_file_path_module_exec.exists():
        config_file_path_module_exec.unlink()
print("-" * 30)


# --- Test 4: Stdio Transport with mcp.client (Simplified from test_server.py) ---
print("--- Test 4: Stdio transport with mcp.client ---")

minimal_config_content_stdio = """
toolbox_title: "Minimal Stdio Test"
toolbox_description: "Minimal Stdio Test Description"
sources:
  - name: "minimal_stdio_source"
    url: "data:text/csv,h1,h2%0Av1,v2"
    description: "A minimal inline CSV for stdio test."
    read_csv_options:
      separator: ","
"""
stdio_debug_log_file = PROJECT_ROOT / "debug_stdio_client.log"
if stdio_debug_log_file.exists():
    stdio_debug_log_file.unlink()

config_file_path_stdio = None 

async def run_stdio_client_test():
    global config_file_path_stdio 
    try:
        from mcp import ClientSession
        from mcp.client.stdio import StdioServerParameters, stdio_client

        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".yaml", dir=PROJECT_ROOT) as tmp_config_file:
            tmp_config_file.write(minimal_config_content_stdio)
            config_file_path_stdio = Path(tmp_config_file.name)

        env = os.environ.copy()
        env["CSV_SOURCES_CONFIG_PATH"] = str(config_file_path_stdio)
        env["MCP_TRANSPORT"] = "stdio"
        env["MCP_SUBPROCESS_LOGFILE"] = str(stdio_debug_log_file)
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONPATH"] = str(SRC_PATH) + os.pathsep + env.get("PYTHONPATH", "")

        print(f"Using config: {config_file_path_stdio}")
        print(f"Expecting log at: {stdio_debug_log_file}")

        server_params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "upphandlat_mcp"],
            env=env,
            cwd=PROJECT_ROOT, # Ensure CWD
        )

        print("Attempting to connect with stdio_client...")
        try:
            async with asyncio.timeout(25): # Increased timeout
                async with stdio_client(server_params) as (read, write):
                    print("stdio_client connected, attempting session...")
                    async with ClientSession(read, write) as session:
                        print("ClientSession created, attempting initialize...")
                        await session.initialize()
                        print("Session initialized.")
                        tools = await session.list_tools()
                        print(f"Listed tools: {[t.name for t in tools.tools if t.name]}")
            print("Stdio client test PASSED.")
        except TimeoutError: 
            print("Stdio client test TIMED OUT during client interaction.")
        except Exception as e:
            print(f"Stdio client test FAILED during client interaction: {type(e).__name__} - {e}")
            import traceback
            traceback.print_exc()

        if stdio_debug_log_file.exists():
            print(f"Contents of {stdio_debug_log_file}:")
            try:
                print(stdio_debug_log_file.read_text())
            except Exception as e_read_stdio:
                print(f"Error reading stdio log file: {e_read_stdio}")

        else:
            print(f"{stdio_debug_log_file} was NOT created.")

    except ImportError:
        print("MCP client libraries not found. Skipping Test 4.")
    except Exception as e:
        print(f"Stdio client test setup FAILED: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if config_file_path_stdio and config_file_path_stdio.exists():
            config_file_path_stdio.unlink()

if __name__ == "__main__":
    # Run Test 4 if mcp is available
    run_test_4 = False
    try:
        import mcp
        run_test_4 = True
    except ImportError:
        print("MCP client libraries not found. Skipping Test 4 async part in main block.")

    if run_test_4:
        asyncio.run(run_stdio_client_test())
    
    print("-" * 30)
    print("All tests finished.")
