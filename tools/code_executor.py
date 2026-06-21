# code executor
# runs python snippets in a sandboxed subprocess
# hard timeout enforced via subprocess.run(..., timeout=...)

import subprocess
import sys
import tempfile
import os
from typing import Optional

# blocked imports that could harm or infinite loops
BLOCKED_IMPORTS = {
    "os.system",
    "subprocess.Popen",
    "__import__",
    "eval(",
    "exec(",
    "open(",
    "socket",
    "requests",
    "urllib",
    "http",
}

def _contains_blocked(code: str) -> Optional[str]:
    for blocked in BLOCKED_IMPORTS:
        if blocked in code:
            return blocked
    return None

def execute_code(code: str, timeout: int = 15) -> dict:
    """ 
    Execute a Python code snippet in an isolated subprocess.

    Args:
        code: Python source code to run.
        timeout: Maximum execution time in seconds (default 15).

    Returns:
        dict with keys 'success', 'stdout', 'stderr', 'exit_code', 'error'.
    """

    if not code or not code.strip():
        return {
            "success": False,
            "stdout": "",
            "stderr": "",
            "exit_code": -1,
            "error": "No code provided"
        }
    

    blocked = _contains_blocked(code)
    if blocked:
        return {
            "success": False,
            "stdout": "",
            "stderr": "",
            "exit_code": -1,
            "error": f"Blocked construct detected: '{blocked}'"
        }
    
    # temp file to traceback line numbers
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", delete=False, encoding="utf-8"
    ) as tmp_file:
        tmp_file.write(code)
        tmp_file_path = tmp_file.name   

    try:
        result = subprocess.run(
            [sys.executable, tmp_file_path],
            capture_output=True,
            text=True,
            timeout=timeout
        )
        
        stdout = result.stdout[:2000]
        stderr = result.stderr[:1000]

        return {
            "success": result.returncode == 0,
            "stdout": stdout,
            "stderr": stderr,
            "exit_code": result.returncode,
            "error": None if result.returncode == 0 else f"Process exited with code {result.returncode}"
        }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "stdout": "",
            "stderr": "",
            "exit_code": -1,
            "error": f"Code execution timed out after {timeout} seconds"
        }
    finally:
        if os.path.exists(tmp_file_path):
            os.unlink(tmp_file_path)