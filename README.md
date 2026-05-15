# DBA.dk Marketplace Bot

Monitor new listings on DBA.dk (Denmark) and message sellers with a static pre-written message when a listing is deemed relevant.

## Features

- Monitors DBA.dk listings in a loop
- Automatically messages sellers for new listings
- Optional LLM review mode:
    - LLM generates search queries/filters from a product description file
    - LLM reviews each ad and decides whether to message or skip
- Saves listing data to prevent duplicate messages
- Random delays between checks to avoid detection

## Prerequisites

- Python 3.8 or higher
- Google Chrome browser
- DBA.dk account

## Installation

1. Create and activate a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
# or
.\venv\Scripts\activate  # Windows
```

2. Install required packages:
```bash
pip install -r requirements.txt
```

3. Create your environment file:
```bash
cp .env.example .env
```

Then edit `.env` and set at least `LLM_API_KEY` if you plan to use `--product-file`.

3. Chrome WebDriver setup is handled automatically by `webdriver_manager`

## Usage

Basic usage (manual query mode):
```bash
python bot.py --query "cykel"
```

LLM mode (recommended):
```bash
export LLM_API_KEY="..."
export LLM_MODEL="gpt-4.1-mini"   # optional
export LLM_BASE_URL="https://api.openai.com/v1"  # optional (OpenAI-compatible)

python bot.py --product-file product_description.md --debug
```

### Arguments

- `--query`: Search term for DBA (manual mode)
- `--product-file`: Path to a product description file (LLM mode)
- `--debug`: Enable debug logging

### LLM environment variables

- `LLM_API_KEY` (required for `--product-file`)
- `LLM_MODEL` (optional; default: `gpt-4.1-mini`)
- `LLM_BASE_URL` (optional; default: `https://api.openai.com/v1`)

### Optional file variables

- `HEADERS_FILE` (default: `headers.json`)
- `MESSAGE_FILE` (default: `message.txt`)

### HTTP compression (garbled response fix)

If you copied browser headers into `headers.json`, you may have `Accept-Encoding: ... br` enabled.
Python `httpx` can decode `gzip`/`deflate` out of the box, but Brotli (`br`) requires an extra package.

- Default behavior: the bot forces `Accept-Encoding` to `gzip, deflate` for its `httpx` requests.
- Override (optional): set `DBA_HTTP_ACCEPT_ENCODING` (e.g. `identity` to disable compression).
- If you really want `br`, install Brotli support (e.g. `pip install brotli`) and set `DBA_HTTP_ACCEPT_ENCODING="br, gzip, deflate"`.

## Important Notes

- When first running the bot, ensure you:
    1. Run the browser in full screen mode
    2. Complete any CAPTCHA if shown
    3. Close any popups that appear
    4. Press ENTER when ready

## Legal Disclaimer

This bot is for educational purposes only. Use at your own risk and responsibility. Make sure to comply with DBA.dk's terms of service.

