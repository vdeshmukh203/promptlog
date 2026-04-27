"""
promptlog: Provider-agnostic LLM interaction logger with SHA-256 tamper detection.

Records prompts, responses, model metadata, and timestamps to structured JSONL
files. Each entry is SHA-256 hashed and the hash chain is verified on read,
making tampering detectable for reproducible research workflows.

Quick start
-----------
>>> from promptlog import PromptLogger, verify_log
>>> logger = PromptLogger("session.jsonl")
>>> logger.log("What is 2+2?", "4", model="gpt-4o")
>>> result = verify_log("session.jsonl")
>>> result.is_valid
True

Auto-intercept all LLM HTTP calls
----------------------------------
>>> import promptlog
>>> promptlog.install("session.jsonl")
>>> # ... make openai / anthropic / gemini calls normally ...
>>> promptlog.uninstall()

GUI viewer
----------
>>> from promptlog.gui import launch_gui
>>> launch_gui("session.jsonl")

Or from the command line::

    python -m promptlog.gui session.jsonl
    promptlog-gui session.jsonl        # if installed via pip
"""

__version__ = "0.1.0"
__author__ = "Vaibhav Deshmukh"
__license__ = "MIT"

from .intercept import install, is_installed, uninstall
from .logger import PromptLogger
from .verify import verify_log

__all__ = [
    "PromptLogger",
    "verify_log",
    "install",
    "uninstall",
    "is_installed",
]
