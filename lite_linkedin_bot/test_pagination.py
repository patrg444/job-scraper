import argparse
import logging
import time
import os
import random
from datetime import datetime
import yaml
from auto_apply_bot.linkedin_bot import EasyApplyBot # Assuming it's in this structure
from auto_apply_bot.searcher import Searcher
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from selenium.webdriver.common.keys import Keys


# Configure logging for the test
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('pagination_test.log', mode='w'), # Log to a file
        logging.StreamHandler() # Log to console
    ]
)
logger = logging.getLogger(__name__)

def load_config(config_path):
    """Loads configuration from a YAML file."""
    try:
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
        logger.info(f"Loaded configuration from {config_path}")
        return config
    except FileNotFoundError:
        logger.error(f"File not found: {config_path}")
        return None
    except yaml.YAMLError as e:
        logger.error(f"Error parsing YAML file: {e}")
        return None

def test_pagination_navigation(config):
    logger.info("--- Starting Pagination Navigation Test ---")
    email = config.get('email')
    password = config.get('password')
    # resume_path is needed for bot init, even if not directly used for applying in this test
    resume_path = config.get('resume_path', 'dummy_resume.pdf') 
    if not os.path.exists(resume_path) and resume_path == 'dummy_resume.pdf':
        # Create a dummy resume if it doesn't exist and is the default, to satisfy bot initialization
        try:
            with open(resume_path, 'w') as f:
                f.write("This is a dummy resume for testing purposes.")
            logger.info(f"Created dummy resume file at {resume_path}")
        except IOError as e:
            logger.error(f"Could not create dummy resume file: {e}")
            # Potentially exit if resume is critical for other parts of bot init not being tested
    
    search_query_singular = config.get('search_query')
    search_queries_plural = config.get('search_queries')

    if search_query_singular and not search_queries_plural:
        search_queries_config = [{'query': search_query_singular, 'location': ''}]
        logger.info(f"Using singular 'search_query' from config: {search_query_singular}")
    elif search_queries_plural:
        search_queries_config = search_queries_plural
        logger.info("Using 'search_queries' list from config.")
    else:
        logger.error("No 'search_query' or 'search_queries' found in config for pagination test.")
        return

    date_filter = config.get('date_filter', 'Past week') # Default to 'Past week' if not specified
    
    # Initialize bot (needed for driver and login)
    # Pass dummy answers if not applying, or load if needed for other parts of bot init
    bot = EasyApplyBot(email, password, resume_path, form_answers={}, openai_api_key=None, use_llm=False)
    
    try:
        bot._init_driver()
        if not bot.driver:
            logger.error("WebDriver initialization failed. Exiting pagination test.")
            return

        if not bot.login():
            logger.error("Login failed. Exiting pagination test.")
            return
        logger.info("Login successful for pagination test.")

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        # Results dir should be created in the Current Working Directory (Hawk)
        results_dir = f"results_pagination_test_{timestamp}" 
        if not os.path.exists(results_dir): # os.path.exists checks relative to CWD if path is relative
             os.makedirs(results_dir, exist_ok=True)
        logger.info(f"Created results directory for pagination test: {os.path.abspath(results_dir)}")
        
        searcher = Searcher(bot.driver, bot.wait)
        searcher.results_dir = results_dir # Ensure searcher can save debug files

        # Perform the initial search to get to the results page
        query_config = search_queries_config[0] # Using the first query for this test
        query = query_config.get('query')
        location = query_config.get('location', '')
        full_query = f"{query} {location}".strip()

        logger.info(f"Performing initial search for query: '{full_query}'")
        searcher.driver.get("https://www.linkedin.com/jobs/")
        searcher._random_delay(2,4)
        
        try:
            # Try to find the main search box on the jobs page
            search_box = searcher.wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "input.jobs-search-box__text-input")))
            search_box.clear()
            for char_s in full_query:
                search_box.send_keys(char_s)
                time.sleep(0.05 + random.random() * 0.1)  # Random typing delay
            searcher._random_delay(0.5, 1.5)
            search_box.send_keys(Keys.ENTER)
        except (TimeoutException, NoSuchElementException):
            # Fallback to global search
            try:
                logger.info("Using global search box as fallback.")
                search_box = searcher.wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "input.search-global-typeahead__input")))
                search_box.clear()
                for char_s in full_query:
                    search_box.send_keys(char_s)
                    time.sleep(0.05 + random.random() * 0.1)
                searcher._random_delay(0.5, 1.5)
                search_box.send_keys(Keys.ENTER)
            except (TimeoutException, NoSuchElementException) as e_search_box:
                logger.error(f"Failed to find any search box: {e_search_box}")
                return
        
        searcher._random_delay(3, 5) # Wait for search results to load
        
        if date_filter:
            logger.info(f"Applying date filter: {date_filter}")
            searcher._apply_date_filter(date_filter)
            searcher._random_delay(2, 3) # Wait for filter application

        # Pagination loop
        max_page_attempts = config.get('pages_to_scan_pagination_test', 5) # Default to 5 pages for test
        logger.info(f"Will attempt to navigate up to {max_page_attempts} pages.")

        for i in range(max_page_attempts):
            current_page_for_log = i + 1 # Page 1 is the initial search result page
            logger.info(f"--- Currently on page {current_page_for_log}. Attempting to navigate to page {current_page_for_log + 1} ---")
            
            logger.info("Scrolling to the bottom of the page before pagination attempt.")
            searcher.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(1.5) 

            try:
                page_state_elements = searcher.driver.find_elements(By.CSS_SELECTOR, "p.jobs-search-pagination__page-state, li.artdeco-pagination__indicator--active button span")
                if page_state_elements:
                    current_page_text = page_state_elements[0].text.strip()
                    logger.info(f"Current pagination state reported by LinkedIn: '{current_page_text}'")
                else:
                    logger.warning("Could not find current page state element using primary selectors.")
            except Exception as e_page_state:
                logger.error(f"Error getting page state: {e_page_state}")

            success = searcher._go_to_next_page()
            if success:
                logger.info(f"Successfully clicked 'Next' (Attempt {i + 1}). Pausing for page load...")
                searcher._random_delay(config.get('pagination_test_delay', 7), config.get('pagination_test_delay', 10)) # Longer delay for page load
            else:
                logger.warning(f"Failed to navigate to next page or no more pages found (Attempt {i + 1}).")
                # Debug HTML is saved by _go_to_next_page on failure
                break
        
        logger.info("--- Pagination Navigation Test Finished ---")

    except Exception as e:
        logger.error(f"An error occurred during pagination test: {e}", exc_info=True)
    finally:
        if bot and bot.driver:
            logger.info("Closing browser for pagination test.")
            bot.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="LinkedIn Pagination Test Bot")
    
    # Determine the project root directory (Hawk) based on the script's location
    # SCRIPT_DIR is Hawk/lite_linkedin_bot
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
    # PROJECT_ROOT_DIR is Hawk
    PROJECT_ROOT_DIR = os.path.dirname(SCRIPT_DIR)
    # Default config path is Hawk/config.yaml
    default_config_path = os.path.join(PROJECT_ROOT_DIR, "config.yaml")
    
    parser.add_argument("--config", type=str, default=default_config_path, help="Path to the configuration YAML file.")
    args = parser.parse_args()
    
    logger.info(f"Attempting to load config from: {os.path.abspath(args.config)}")
    config_data = load_config(args.config)
    if not config_data:
        logger.error("Failed to load configuration. Exiting.")
    else:
        test_pagination_navigation(config_data)
