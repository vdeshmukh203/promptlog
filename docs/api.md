# promptlog API Reference

## PromptLogger

```python
from promptlog import PromptLogger
logger = PromptLogger("session.jsonl")
logger.log(prompt, response, model, metadata={"temperature": 0.7})
```

## verify_log

```python
from promptlog import verify_log
result = verify_log("session.jsonl")
print(result.is_valid, result.tampered_entries)
```

## promptlog.install

```python
import promptlog
promptlog.install("session.jsonl")
# all HTTP to OpenAI/Anthropic/Google auto-logged
promptlog.uninstall()
```
