"""Bounded terminal diagnostics; never log provider bodies or credentials."""

import logging
import re
import traceback

logger = logging.getLogger("uvicorn.error")


def log_diagnostic(code: str, message: str, *, run_id: str = "-", secret: str = "") -> None:
    text = str(message)
    if secret:
        text = text.replace(secret, "[redacted]")
    text = re.sub(r"\bsk-[A-Za-z0-9_-]+", "[redacted]", text)
    text = re.sub(r"(?i)\bBearer\s+\S+", "Bearer [redacted]", text)
    # One physical log line, without terminal control sequences or huge payloads.
    text = " ".join("".join(c for c in text if c.isprintable() or c in "\r\n\t").split())[:2000]
    safe_code = re.sub(r"[^A-Za-z0-9_]", "", code)[:80]
    safe_run = re.sub(r"[^A-Za-z0-9_-]", "", run_id)[:64]
    logger.warning("%s run=%s: %s", safe_code, safe_run, text)


def log_exception(error: Exception, *, run_id: str = "-") -> None:
    # Exception strings/locals may include raw provider payloads and secrets.
    # Frame locations and the exception type remain useful for debugging.
    frames = traceback.extract_tb(error.__traceback__)
    locations = " -> ".join(f"{frame.filename}:{frame.lineno} ({frame.name})" for frame in frames[-8:])
    log_diagnostic(type(error).__name__, locations or "No traceback available", run_id=run_id)
