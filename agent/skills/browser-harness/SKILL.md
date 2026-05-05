---
name: browser-harness
description: |
  Browser automation via direct CDP (Chrome DevTools Protocol) control.
  USE WHEN user wants to control a browser by writing code, not through pre-built commands.
  USE WHEN user wants the agent to write its own browser control functions.
  USE WHEN opencli is not available or user prefers direct CDP control.
allowed-tools: cdp_connect, cdp_execute, cdp_get_state, cdp_edit_helpers, task_complete
---

# Browser Harness — Direct CDP Control

Control Chrome by writing code that speaks CDP directly. No pre-built abstractions — you write what you need.

## Prerequisites

Chrome must be running with remote debugging enabled:
```bash
# Windows
"C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="%USERPROFILE%\.cdp_profile"

# Or use Edge
"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" --remote-debugging-port=9222 --user-data-dir="%USERPROFILE%\.cdp_profile_edge"
```

## Cookie Auto-Persistence

Login state is automatically preserved across sessions. No manual cookie management needed.

- **On connect**: Cookies are automatically loaded from `.cdp_state/cookies.json`
- **On disconnect**: Cookies are automatically saved to the file
- **Periodic flush**: Cookies are saved every 120 seconds to prevent data loss from crashes
- **Custom path**: Pass `cookie_store_path` to `cdp_connect()` to use a different file

Workflow:
1. First session: `cdp_connect()` -> login to websites -> cookies saved on disconnect
2. Next session: `cdp_connect()` -> cookies auto-loaded -> already logged in

## Core Workflow

1. **Connect**: `cdp_connect()` — connect to Chrome
2. **Observe**: `cdp_get_state()` — see current page state
3. **Act**: `cdp_execute(function='navigate', args={'url': '...'})` — control browser
4. **Self-heal**: If function missing → `cdp_edit_helpers(name='...', code='...')` → retry

## Available Helper Functions

| Function | Args | Description |
|----------|------|-------------|
| `navigate` | `url: str` | Navigate to URL |
| `get_url` | — | Get current URL |
| `get_title` | — | Get page title |
| `evaluate` | `expression: str` | Execute JavaScript |
| `query_selector` | `selector: str` | Find element by CSS selector |
| `query_selector_all` | `selector: str` | Find all matching elements |
| `click` | `selector: str` | Click element by selector |
| `type_text` | `text: str` | Type text into focused input |
| `press_key` | `key: str` | Press key (Enter, Tab, Escape, etc.) |
| `screenshot` | `path: str = None` | Capture screenshot |
| `scroll_down` | `amount: int = 300` | Scroll down |
| `scroll_up` | `amount: int = 300` | Scroll up |
| `wait_for_selector` | `selector: str, timeout: float = 5.0` | Wait for element |
| `get_interactive_elements` | — | List all interactive elements |

## Self-Healing Loop

When you need a function that doesn't exist:

1. `cdp_execute` returns `missing_function` error
2. Write the function using `cdp_client.execute()` for CDP commands
3. Add it with `cdp_edit_helpers(name='function_name', code='...')`
4. Retry `cdp_execute(function='function_name', args={...})`

### Example: Adding upload_file

```python
# Step 1: Try to use it
cdp_execute(function='upload_file', args={'selector': 'input[type=file]', 'file_path': '/path/to/file'})

# Step 2: Get missing_function error

# Step 3: Add the function
cdp_edit_helpers(
  name='upload_file',
  code='''
async def upload_file(selector: str, file_path: str):
    result = await cdp_client.execute('DOM.querySelector', {'nodeId': 1, 'selector': selector})
    node_id = result.get('nodeId', 0)
    if not node_id:
        return False
    await cdp_client.execute('DOM.setFileInputFiles', {'files': [file_path], 'nodeId': node_id})
    return True
'''
)

# Step 4: Retry
cdp_execute(function='upload_file', args={'selector': 'input[type=file]', 'file_path': '/path/to/file'})
```

## Raw CDP Commands

For operations not covered by helpers:

```python
cdp_execute(
  function='raw',
  method='Network.enable',
  params={}
)
```

Common CDP domains: Page, DOM, Runtime, Input, Network, Emulation, Target

## Tips

1. Always `cdp_get_state()` before acting — know what's on the page
2. Use `evaluate()` for data extraction — `JSON.stringify(...)` for complex data
3. Use `click()` for interaction — it handles scrolling and coordinates
4. Write helpers for repeated patterns — they persist for the session
5. Check `available_functions` in `cdp_connect` response for current helpers
