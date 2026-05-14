import httpx
import re
import json
import logging
import argparse
from dataclasses import dataclass
from typing import Any, Optional
from bs4 import BeautifulSoup
from urllib.parse import urlencode
from datetime import datetime
import os
import random

try:
    from dotenv import load_dotenv  # type: ignore
except Exception:  # pragma: no cover
    load_dotenv = None

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.keys import Keys

import time


@dataclass(frozen=True)
class DbaSearchParams:
    q: str
    location: str = "0.200001"
    price_from: Optional[str] = None
    price_to: Optional[str] = None
    sort: str = "PUBLISHED_DESC"

    def to_query_params(self) -> dict[str, str]:
        params: dict[str, str] = {
            "location": self.location,
            "q": self.q,
            "sort": self.sort,
        }
        if self.price_from is not None:
            params["price_from"] = str(self.price_from)
        if self.price_to is not None:
            params["price_to"] = str(self.price_to)
        return params


@dataclass(frozen=True)
class ListingInfo:
    url: str
    listing_id: str
    title: str
    price: Optional[str]
    currency: Optional[str]
    location: Optional[str]
    description: str


@dataclass(frozen=True)
class LlmDecision:
    send_message: bool
    confidence: float
    reason: str


class LlmClient:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str = "https://api.openai.com/v1",
        timeout_s: float = 60.0,
    ):
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout_s = timeout_s

    def chat_json(self, *, system: str, user: str) -> dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": self._model,
            "temperature": 0.2,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "response_format": {"type": "json_object"},
        }

        url = f"{self._base_url}/chat/completions"
        with httpx.Client(timeout=self._timeout_s) as client:
            resp = client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()

        content = (
            data.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
            .strip()
        )
        if not content:
            raise ValueError("LLM returned empty content")
        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            raise ValueError(f"LLM did not return valid JSON: {e}\nRaw: {content[:500]}") from e


def get_data_dir() -> str:
    data_dir = os.path.join(os.path.dirname(__file__), ".data")
    os.makedirs(data_dir, exist_ok=True)
    return data_dir


def get_listings_file() -> str:
    return os.path.join(get_data_dir(), "listings.txt")


def load_headers() -> dict[str, str]:
    headers_file = os.getenv("HEADERS_FILE", "headers.json")
    with open(headers_file, "r") as file:
        data = json.load(file)
    if not isinstance(data, dict):
        raise ValueError(f"{headers_file} must contain a JSON object")
    return {str(k): str(v) for k, v in data.items()}


def load_product_description(product_file: str) -> str:
    with open(product_file, "r", encoding="utf-8") as f:
        text = f.read().strip()
    if not text:
        raise ValueError(f"Product description file is empty: {product_file}")
    return text

def setup_logging(debug=False):
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )

def search_dba_listings(search: DbaSearchParams, headers: dict[str, str], debug: bool = False) -> list[str]:
    logger = logging.getLogger(__name__)
    
    params = search.to_query_params()
    logger.info(f"Request parameters: {params}")

    url = f'https://www.dba.dk/recommerce/forsale/search?{urlencode(params)}'
    logger.debug(f"Request URL: {url}")

    try:
        logger.debug("Making HTTP/2 request...")
        # Use httpx with HTTP/2 support
        with httpx.Client(http2=True) as client:
            response = client.get(url, headers=headers)
            response.raise_for_status()
            logger.debug(f"Response status code: {response.status_code}")
            logger.debug(f"HTTP version: {response.http_version}")
            # Add this inside the try block after the response
            logger.debug("Response headers:")
            for key, value in response.headers.items():
                logger.debug(f"{key}: {value}")

            # Update the response body logging to show first 1000 characters
            logger.debug(f"First 1000 chars of response: {response.text[:1000]}")

        # Parse HTML
        logger.debug("Parsing HTML response...")
        soup = BeautifulSoup(response.text, 'html.parser')
        
        all_listings = [a['href'] for a in soup.find_all('a', href=re.compile(r'https://www.dba.dk/recommerce/forsale/item/\d+'))]

        logger.debug(f"Total urls found: {all_listings}")

        logger.info(f"Total urls found: {len(all_listings)}")
        
        listings_file = get_listings_file()
        logger.debug(f"Using listings file path: {listings_file}")

        # Load existing listings from file
        if os.path.exists(listings_file):
            with open(listings_file, 'r') as file:
                existing_listings = [line.strip() for line in file.readlines()]
                logger.info(f"Loaded {len(existing_listings)} existing listings from file")
        else:
            existing_listings = []
            logger.info("No existing listings file found, starting with an empty list")

        new_listings = [listing for listing in all_listings if listing not in existing_listings]

        logger.info(f"All new listings found: {new_listings}")

        # Log total new listings
        logger.info(f"Total new listings found: {len(new_listings)}")

        return new_listings

    except httpx.RequestError as e:
        logger.error(f"Error making request: {e}")
    except Exception as e:
        logger.error(f"Error processing data: {e}")

    return []

from selenium.webdriver.common.by import By
import debugpy


def fetch_listing_info(url: str, headers: dict[str, str], debug: bool = False) -> ListingInfo:
    logger = logging.getLogger(__name__)
    listing_id = url.rstrip("/").split("/")[-1]

    with httpx.Client(http2=True, timeout=30.0) as client:
        resp = client.get(url, headers=headers)
        resp.raise_for_status()
        html = resp.text

    soup = BeautifulSoup(html, "html.parser")

    title = ""
    og_title = soup.find("meta", property="og:title")
    if og_title and og_title.get("content"):
        title = og_title.get("content", "").strip()
    if not title and soup.title and soup.title.string:
        title = soup.title.string.strip()

    description = ""
    og_desc = soup.find("meta", property="og:description")
    if og_desc and og_desc.get("content"):
        description = og_desc.get("content", "").strip()
    if not description:
        meta_desc = soup.find("meta", attrs={"name": "description"})
        if meta_desc and meta_desc.get("content"):
            description = meta_desc.get("content", "").strip()

    # Fallback: take a bounded chunk of visible text.
    if not description:
        text = soup.get_text("\n", strip=True)
        description = "\n".join([line for line in text.splitlines() if line][:40])

    price = None
    currency = None
    location = None

    # Try to parse JSON-LD structured data if present.
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            data = json.loads(script.get_text(strip=True) or "{}")
        except Exception:
            continue

        candidates: list[dict[str, Any]] = []
        if isinstance(data, list):
            candidates = [d for d in data if isinstance(d, dict)]
        elif isinstance(data, dict):
            candidates = [data]

        for obj in candidates:
            offers = obj.get("offers")
            if isinstance(offers, dict):
                if price is None and offers.get("price") is not None:
                    price = str(offers.get("price"))
                if currency is None and offers.get("priceCurrency") is not None:
                    currency = str(offers.get("priceCurrency"))
            if location is None:
                loc = obj.get("availableAtOrFrom") or obj.get("areaServed") or obj.get("location")
                if isinstance(loc, dict) and loc.get("name"):
                    location = str(loc.get("name"))
            if title and description and price:
                break

    if debug:
        logger.debug(
            "Listing extracted: id=%s title=%r price=%r currency=%r location=%r",
            listing_id,
            title,
            price,
            currency,
            location,
        )

    return ListingInfo(
        url=url,
        listing_id=listing_id,
        title=title,
        price=price,
        currency=currency,
        location=location,
        description=description,
    )


def llm_generate_search_plan(llm: LlmClient, product_description: str) -> list[DbaSearchParams]:
    system = (
        "You generate DBA.dk search queries and filters for Denmark. "
        "DBA is a Danish marketplace; many listings are in Danish. "
        "Return ONLY JSON."
    )

    user = (
        "Given this product description, generate 2-5 search plans for DBA.dk. "
        "Use Danish query terms where appropriate (you may include English equivalents as separate queries). "
        "Each plan must be an object with keys: q (string), price_from (string or null), "
        "price_to (string or null), location (string, keep default '0.200001' unless you have a strong reason), "
        "sort (string, use 'PUBLISHED_DESC').\n\n"
        "Product description:\n"
        f"{product_description}\n\n"
        "Output schema:\n"
        "{\n"
        "  \"search_plans\": [\n"
        "    {\"q\": \"...\", \"price_from\": null, \"price_to\": null, \"location\": \"0.200001\", \"sort\": \"PUBLISHED_DESC\"}\n"
        "  ]\n"
        "}"
    )

    data = llm.chat_json(system=system, user=user)
    plans_raw = data.get("search_plans", [])
    if not isinstance(plans_raw, list) or not plans_raw:
        raise ValueError("LLM did not return search_plans list")

    plans: list[DbaSearchParams] = []
    for item in plans_raw:
        if not isinstance(item, dict) or not item.get("q"):
            continue
        plans.append(
            DbaSearchParams(
                q=str(item.get("q")),
                location=str(item.get("location") or "0.200001"),
                price_from=None if item.get("price_from") is None else str(item.get("price_from")),
                price_to=None if item.get("price_to") is None else str(item.get("price_to")),
                sort=str(item.get("sort") or "PUBLISHED_DESC"),
            )
        )

    if not plans:
        raise ValueError("LLM returned no usable search plans")
    return plans


def llm_decide_send_message(llm: LlmClient, product_description: str, listing: ListingInfo) -> LlmDecision:
    system = (
        "You decide whether a DBA.dk listing matches what the user wants. "
        "Return ONLY JSON."
    )

    user = (
        "Given the product description and listing details, decide if it is worth messaging the seller. "
        "If the listing is likely a match and not obviously incompatible, choose send_message=true. "
        "If unclear, lean toward send_message=false. Consider Danish text.\n\n"
        "Product description:\n"
        f"{product_description}\n\n"
        "Listing:\n"
        f"- url: {listing.url}\n"
        f"- title: {listing.title}\n"
        f"- price: {listing.price} {listing.currency or ''}\n"
        f"- location: {listing.location or ''}\n"
        f"- description: {listing.description[:1500]}\n\n"
        "Output schema:\n"
        "{\n"
        "  \"send_message\": true|false,\n"
        "  \"confidence\": 0.0-1.0,\n"
        "  \"reason\": \"short explanation\"\n"
        "}"
    )

    data = llm.chat_json(system=system, user=user)
    send_message = bool(data.get("send_message"))
    confidence_raw = data.get("confidence", 0.0)
    try:
        confidence = float(confidence_raw)
    except Exception:
        confidence = 0.0
    reason = str(data.get("reason", "")).strip() or "(no reason provided)"
    confidence = max(0.0, min(1.0, confidence))
    return LlmDecision(send_message=send_message, confidence=confidence, reason=reason)


def process_listings(
    driver,
    listings: list[str],
    *,
    headers: dict[str, str],
    product_description: Optional[str] = None,
    llm: Optional[LlmClient] = None,
    debug: bool = False,
):
    for listing in listings:

        listings_file = get_listings_file()
        existing_listings: list[str] = []
        if os.path.exists(listings_file):
            with open(listings_file, "r") as file:
                existing_listings = [line.strip() for line in file.readlines()]

        if listing in existing_listings:
            logging.info(f"Listing already processed: {listing}")
            continue

        if llm is not None and product_description is not None:
            try:
                info = fetch_listing_info(listing, headers=headers, debug=debug)
                decision = llm_decide_send_message(llm, product_description, info)
                logging.info(
                    "LLM decision for %s: send=%s conf=%.2f reason=%s",
                    listing,
                    decision.send_message,
                    decision.confidence,
                    decision.reason,
                )
                if not decision.send_message:
                    # Mark as processed so we don't reconsider it forever.
                    os.makedirs(os.path.dirname(listings_file), exist_ok=True)
                    with open(listings_file, "a") as file:
                        file.write(f"{listing}\n")
                    logging.info(f"Skipped (LLM) and recorded listing: {listing}")
                    continue
            except Exception as e:
                logging.error(f"LLM review failed for {listing}: {e}")
                # If LLM fails, play it safe and skip messaging.
                os.makedirs(os.path.dirname(listings_file), exist_ok=True)
                with open(listings_file, "a") as file:
                    file.write(f"{listing}\n")
                logging.info(f"Skipped (LLM error) and recorded listing: {listing}")
                continue

        listing_id = listing.split('/')[-1]
        driver.get(f"https://www.dba.dk/messages/new/{listing_id}")
        time.sleep(5)

        # click message seller button
        try:
            text_area = driver.find_element(By.XPATH, '/html/body/div[1]/main/div/div[2]/section[2]/div[3]/div/textarea')
            
            if text_area:
                logging.debug("Found text area")
            else:
                logging.error("Text area not found")

            message_file = os.getenv("MESSAGE_FILE", "message.txt")
            with open(message_file, 'r', encoding='utf-8') as file:
                message = file.read().strip()
                logging.debug(f"Read message from file: {message}")
                
            text_area.send_keys(message)
            logging.debug(f"Entered message: {message}")
            time.sleep(5)

            send_button = driver.find_element(By.XPATH, '/html/body/div[1]/main/div/div[2]/section[2]/div[3]/div/button')
            if send_button:
                send_button.click()
                logging.debug("Clicked 'Send' button")
                time.sleep(10)
            else:
                logging.error("'Send' button not found")

        except Exception as e:
            logging.error(f"Error sending message to seller: {e}")
        finally:
            # Append new listing to file
            os.makedirs(os.path.dirname(listings_file), exist_ok=True)
            with open(listings_file, 'a') as file:
                file.write(f"{listing}\n")
            logging.info(f"Appended new listing to file: {listing}")
        

def driver_setup():
    options = Options()
    options.add_argument('--disable-dev-shm-usage')
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    return driver

def login_to_dba(driver):
    # Add your Facebook login credentials here
    print("Loggin in to DBA.dk")
    driver.get("https://www.dba.dk/auth/login")

    print("\n" + "═"*80)
    print("║" + " "*78 + "║")
    print("║" + "🔴 IMPORTANT SETUP INSTRUCTIONS".center(77) + "║")
    print("║" + " "*78 + "║")
    print("║" + "1. Make sure the browser window is in FULL SCREEN mode".center(78) + "║")
    print("║" + "2. Login to DBA and complete the CAPTCHA if shown".center(78) + "║")
    print("║" + "3. Close any popups that appear".center(78) + "║")
    print("║" + "4. Press ENTER when ready to continue".center(78) + "║")
    print("║" + " "*78 + "║")
    print("═"*80 + "\n")
    logging.info("Waiting for user input...")
    input()  # Wait for user to press ENTER

def create_data_directory():
    # Backwards-compatible alias; this bot uses .data for state.
    data_dir = get_data_dir()
    logging.info(f"Using data directory at {data_dir}")
    return data_dir

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="DBA.dk Marketplace Bot",
        epilog="Example usage:\n"
               "  python bot.py --query 'cykel'\n"
               "  python bot.py --product-file product_description.md --debug",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument('-d', '--debug', action='store_true', help='Enable debug logging')

    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--query', type=str, help='Search term for DBA (manual mode)')
    mode.add_argument('--product-file', type=str, help='Path to product description file (LLM mode)')

    args = parser.parse_args()

    if load_dotenv is not None:
        load_dotenv()

    if args.debug:
        debugpy.listen(("0.0.0.0", 5678))
        print("Waiting for debugger attachment...")
        debugpy.wait_for_client()

    setup_logging(args.debug)
    logging.info("Logging setup complete")

    create_data_directory()
    logging.info("Data directory created")

    headers = load_headers()
    logging.info("Loaded request headers")

    llm: Optional[LlmClient] = None
    product_description: Optional[str] = None
    search_plans: Optional[list[DbaSearchParams]] = None

    if args.product_file:
        product_description = load_product_description(args.product_file)
        api_key = os.getenv("LLM_API_KEY")
        if not api_key:
            raise SystemExit("LLM_API_KEY is required when using --product-file")
        model = os.getenv("LLM_MODEL", "gpt-4.1-mini")
        base_url = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
        llm = LlmClient(api_key=api_key, model=model, base_url=base_url)
        logging.info("LLM enabled: model=%s base_url=%s", model, base_url)
        search_plans = llm_generate_search_plan(llm, product_description)
        logging.info("LLM generated %d search plan(s)", len(search_plans))

    # Must happen only at startup
    driver = driver_setup()
    logging.info("Driver setup complete")
    
    login_to_dba(driver=driver)

    logging.info("Login complete")

    try:
        logging.info("Starting main loop...")
        while True:
            logging.info("Checking DBA.dk for new listings...")
            all_new_listings: list[str] = []

            if search_plans is not None:
                for plan in search_plans:
                    new_listings = search_dba_listings(plan, headers=headers, debug=args.debug)
                    all_new_listings.extend(new_listings)
            else:
                all_new_listings = search_dba_listings(DbaSearchParams(q=args.query), headers=headers, debug=args.debug)

            # De-duplicate while keeping order
            seen: set[str] = set()
            new_listings = [u for u in all_new_listings if not (u in seen or seen.add(u))]
            logging.info(f"Found {len(new_listings)} new listings")
            if new_listings:
                logging.info("Processing new listings...")
                process_listings(
                    driver=driver,
                    listings=new_listings,
                    headers=headers,
                    product_description=product_description,
                    llm=llm,
                    debug=args.debug,
                )
            
            # Random wait between 5 and 15 minutes
            wait_time = random.randint(300, 900)
            logging.info(f"Waiting {wait_time/60:.1f} minutes until next check...")
            
            # Countdown timer
            start_time = time.time()
            while (time.time() - start_time) < wait_time:
                remaining = wait_time - int(time.time() - start_time)
                mins, secs = divmod(remaining, 60)
                print(f"\033[1;32mTime remaining: {mins:02d}:{secs:02d}\033[0m", end='\r')
                time.sleep(1)
            print() # Clear the line
            
    except KeyboardInterrupt:
        logging.info("Received CTRL+C, shutting down...")

    driver.quit()