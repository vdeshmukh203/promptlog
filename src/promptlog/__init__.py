"""
promptlog: Provider-agnostic LLM interaction logger with SHA-256 tamper detection.

Records prompts, responses, model metadata, and timestamps to structured JSONL
files. Each entry is SHA-256 hashed and the hash chain is verified on read,
making tampering detectable for reproducible research workflows.
"""

__version__ = "0.1.0"
__author__ = "Vaibhav Deshmukh"
__license__ = "MIT"

from .gui import launch as launch_gui
from .intercept import install, is_installed, uninstall
from .logger import PromptLogger
from .verify import verify_log

__all__ = [
    "PromptLogger",
    "verify_log",
    "install",
    "uninstall",
    "is_installed",
    "launch_gui",
]
