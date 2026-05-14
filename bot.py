import httpx
import re
import json
import logging
import argparse
from bs4 import BeautifulSoup
from urllib.parse import urlencode
from datetime import datetime
import os
import random

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.keys import Keys

import time

def setup_logging(debug=False):
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )

def get_facebook_marketplace_data(query, debug=False):
    logger = logging.getLogger(__name__)
    
    # Request parameters
    params = {
        'location': '0.200001',
        'price_from': '1500',
        'price_to': '3500',
        'q': query,
        'sort': 'PUBLISHED_DESC'
    }
    
    logger.info(f"Request parameters: {params}")

    # Request headers, open from headers.json file
    with open('headers.json', 'r') as file:
        headers = json.load(file)  

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
        
        # Create data directory if it doesn't exist
        data_dir = os.path.join(os.path.dirname(__file__), '.data')
        if not os.path.exists(data_dir):
            os.makedirs(data_dir)
            logger.info(f"Created data directory at {data_dir}")

        listings_file = os.path.join(data_dir, 'listings.txt')
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

from selenium.webdriver.common.by import By
import debugpy


def process_listings(driver, listings: list[str]):
    for listing in listings:
        
        with open("./.data/listings.txt", 'r') as file:
            existing_listings = [line.strip() for line in file.readlines()]
            if listing in existing_listings:
                logging.info(f"Listing already processed: {listing}")
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

            message = f"Hi there! Is this bike still available?"
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
            os.makedirs(os.path.dirname("./.data/listings.txt"), exist_ok=True)
            with open("./.data/listings.txt", 'a') as file:
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
    data_dir = os.path.join(os.path.dirname(__file__), 'data')
    if not os.path.exists(data_dir):
        os.makedirs(data_dir)
        logging.info(f"Created data directory at {data_dir}")
    return data_dir

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Facebook Marketplace Bot",
        epilog="Example usage:\n"
               "  python bot.py --query 'bicycle'\n"
               "  python bot.py --query 'laptop' --debug",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument('-d', '--debug', action='store_true', help='Enable debug logging')
    parser.add_argument('--query', type=str, required=True, help='Search term for marketplace')
    parser.add_argument('--max-price', type=str, default='400', help='Maximum price (default: 400)')
    parser.add_argument('--days-since-listed', type=str, default='30', help='Days since listed (default: 30)')
    parser.add_argument('--sort-by', type=str, default='creation_time_descend', help='Sort order (default: creation_time_descend)')
    parser.add_argument('--exact', type=str, default='false', help='Exact match (default: false)')
    args = parser.parse_args()

    if args.debug:
        debugpy.listen(("0.0.0.0", 5678))
        print("Waiting for debugger attachment...")
        debugpy.wait_for_client()

    setup_logging(args.debug)
    logging.info("Logging setup complete")

    create_data_directory()
    logging.info("Data directory created")

    # Must happen only at startup
    driver = driver_setup()
    logging.info("Driver setup complete")
    
    login_to_dba(driver=driver)

    logging.info("Login complete")

    try:
        logging.info("Starting main loop...")
        while True:
            logging.info("Checking Marketplace for new listings...")
            new_listings = get_facebook_marketplace_data(args.query, args.debug)
            logging.info(f"Found {len(new_listings)} new listings")
            if new_listings:
                logging.info("Processing new listings...")
                process_listings(driver=driver, listings=new_listings)
            
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