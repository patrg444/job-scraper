import time
import random
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, StaleElementReferenceException
import urllib.parse
import os
import logging # Added import for logging

logger = logging.getLogger(__name__) # Added logger instance

class Searcher:
    """
    Class to handle LinkedIn job searching functionality.
    """
    def __init__(self, driver, wait):
        """
        Initialize with an existing driver and wait objects.
        """
        self.driver = driver
        self.wait = wait
        self.job_urls = set()  # Using a set to avoid duplicates
    
    def _random_delay(self, min_seconds=1.0, max_seconds=3.0):
        """Add a random delay between actions to simulate human behavior."""
        delay = min_seconds + (max_seconds - min_seconds) * random.random()
        time.sleep(delay)
    
    def search_jobs(self, search_query, date_filter=None, pages_to_scan=3, max_links=50):
        logger.info(f"Searcher.search_jobs: Entered with pages_to_scan={pages_to_scan}, max_links={max_links}, date_filter='{date_filter}'") # Added more detail
        """
        Search for jobs on LinkedIn based on the provided query and filters.
        
        Args:
            search_query: The search string including job title, location, and "easy apply"
            date_filter: Time filter for job posts (e.g., "Past 24 hours", "Past week")
            pages_to_scan: Maximum number of pages to scan
            max_links: Maximum number of job links to collect
            
        Returns:
            List of job URLs
        """
        try:
            print(f"Searching for jobs with query: '{search_query}'")
            
            # Interpret max_links == 0 as unlimited
            effective_max_links = float('inf') if max_links == 0 else max_links
            
            # Navigate to LinkedIn Jobs
            self.driver.get("https://www.linkedin.com/jobs/")
            self._random_delay(2, 4)
            
            # Find and fill the search box
            try:
                # Try to find the main search box on the jobs page
                search_box = self.wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "input.jobs-search-box__text-input")))
                search_box.clear()
                for char in search_query:
                    search_box.send_keys(char)
                    time.sleep(0.05 + random.random() * 0.1)  # Random typing delay
                self._random_delay(0.5, 1.5)
                search_box.send_keys(Keys.ENTER)
            except (TimeoutException, NoSuchElementException):
                # Fallback to global search
                try:
                    print("Using global search box")
                    search_box = self.wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "input.search-global-typeahead__input")))
                    search_box.clear()
                    for char in search_query:
                        search_box.send_keys(char)
                        time.sleep(0.05 + random.random() * 0.1)
                    self._random_delay(0.5, 1.5)
                    search_box.send_keys(Keys.ENTER)
                except (TimeoutException, NoSuchElementException) as e:
                    print(f"Failed to find search box: {e}")
                    return list(self.job_urls)
            
            # Wait for search results to load
            self._random_delay(3, 5)
            
            # Apply date filter if specified
            if date_filter:
                self._apply_date_filter(date_filter)
                self._random_delay(2, 3)
            
            # Collect job URLs
            page_count = 0
            logger.info(f"Searcher.search_jobs: Starting pagination. Configured pages_to_scan={pages_to_scan}, effective_max_links (per page for _collect_job_urls_on_page)={effective_max_links}")
            
            # The loop should primarily be controlled by pages_to_scan.
            # The effective_max_links will be used by _collect_job_urls_on_page to limit collection *on that specific page* if needed,
            # but the searcher should attempt to scan all configured pages.
            # The overall total limit will be handled in main.py.
            while page_count < pages_to_scan:
                page_count += 1 
                logger.info(f"Searcher.search_jobs: Loop iteration. Current page_count={page_count} (attempting to scan page {page_count})")
                
                print(f"Scanning page {page_count} for job listings...")
                
                # Pass effective_max_links to _collect_job_urls_on_page. 
                # This means if a single page has more than 'effective_max_links' (e.g., 25), it will stop collecting from *that page* at that limit.
                # However, the overall collection across pages can exceed this if pages_to_scan is > 1.
                # If we want to collect ALL from each page up to pages_to_scan, then _collect_job_urls_on_page should get float('inf')
                # For now, let's keep passing effective_max_links, which is 25 from config.
                # This means it will try to get up to 25 links *per page* for *pages_to_scan* pages.
                # The total number of URLs collected could be up to pages_to_scan * effective_max_links.
                # The previous logic was capping the *total* at effective_max_links.
                
                # Let's clarify: if max_links from config is meant to be a TOTAL limit for the searcher,
                # then the original loop `while page_count < pages_to_scan and len(self.job_urls) < effective_max_links:` was correct.
                # If the user wants to scan 5 pages and get *all* jobs from those 5 pages, then `max_links` in config
                # should be set very high or 0, and the `len(self.job_urls) < effective_max_links` check should be removed from the while loop.

                # Based on user feedback "there should be more than 25", it implies they want all pages scanned.
                # So, the `len(self.job_urls) < effective_max_links` should be removed from the main pagination loop.
                # The `_collect_job_urls_on_page` will still respect the `limit` passed to it, which is `effective_max_links`.
                # This means it will collect up to `effective_max_links` (25) from *each* page.
                # Total collected will be roughly pages_to_scan * 25 (if each page has >= 25 links).
                
                # The `_collect_job_urls_on_page` method itself has a `limit` parameter.
                # The `effective_max_links` is passed to it.
                # The issue was the global cap in the `while` loop here.
                
                self._collect_job_urls_on_page(effective_max_links) # effective_max_links is 25 from config
                logger.info(f"Searcher.search_jobs: After _collect_job_urls_on_page for page {page_count}, collected {len(self.job_urls)} total URLs.")
                print(f"Collected {len(self.job_urls)} unique job URLs so far")
                
                # If this was the last page to scan, break
                if page_count >= pages_to_scan:
                    logger.info(f"Searcher.search_jobs: Reached pages_to_scan limit ({pages_to_scan}). Will not attempt to go to next page. Current page_count={page_count}.")
                    break

                # Try to click next page
                logger.info(f"Searcher.search_jobs: Attempting to go to next page from page {page_count}.")
                print("Pausing for 30 seconds for inspection before attempting to go to the next page...") # Kept original print
                time.sleep(30)

                # Ensure the entire page is scrolled to the bottom to reveal pagination controls
                self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(1) # Allow time for any lazy-loaded elements to appear
                
                went_to_next = self._go_to_next_page()
                logger.info(f"Searcher.search_jobs: _go_to_next_page() returned: {went_to_next}")
                if not went_to_next:
                    print("No more pages to scan") # Kept original print
                    logger.info("Searcher.search_jobs: _go_to_next_page() indicated no more pages or failed. Breaking loop.")
                    # Save page source if pagination fails (this logic is now inside _go_to_next_page)
                    # try:
                    #    timestamp = time.strftime("%Y%m%d-%H%M%S")
                    #    # Ensure results_dir is accessible or use a default path
                    #    results_dir_path = getattr(self, 'results_dir', '.')
                    #    if not os.path.isdir(results_dir_path):
                    #         # Attempt to create if it doesn't exist, or use a fallback
                    #        try:
                    #            os.makedirs(results_dir_path, exist_ok=True)
                    #        except OSError: # If creation fails (e.g. permission issues)
                    #            results_dir_path = "." # Fallback to current directory

                    #    debug_html_path = os.path.join(results_dir_path, f"debug_pagination_fail_{timestamp}.html")
                    #    with open(debug_html_path, 'w', encoding='utf-8') as f:
                    #        f.write(self.driver.page_source)
                    #    print(f"Saved page source for pagination failure to {debug_html_path}")
                    # except Exception as e_save:
                    #    print(f"Error saving debug page source on pagination failure: {e_save}")
                    break
                
                logger.info(f"Searcher.search_jobs: Successfully navigated from page {page_count}. Loop will continue for page {page_count + 1}.")
                self._random_delay(2, 4) # Delay before processing next page
            
            logger.info(f"Searcher.search_jobs: Exited pagination loop. Final page_count={page_count}. Total URLs collected={len(self.job_urls)}.")
            return list(self.job_urls)
        
        except Exception as e:
            logger.error(f"Error during job search: {e}", exc_info=True) # Added exc_info=True
            return list(self.job_urls)
    
    def _apply_date_filter(self, date_filter):
        """Apply date posted filter."""
        try:
            print(f"Applying date filter: {date_filter}")
            
            # First, wait for the search results page to fully load, specifically the job list
            print("Waiting for job list (e.g., ul.semantic-search-results-list) to be present...")
            # Using a selector known to work later for the job list itself
            self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "ul.semantic-search-results-list, div.jobs-search-results-list")))
            print("Job list container found.")
            self._random_delay(2, 3)
            
            # Click the "Date posted" filter button
            print("Attempting to click 'Date posted' filter button...")
            # Primary selector based on provided HTML, with fallbacks
            date_filter_button_selectors = [
                "button#searchFilter_timePostedRange", # Preferred based on provided HTML
                "button[aria-label='Date posted filter']",
                "//button[contains(.,'Date posted') and contains(@class, 'search-reusables__filter-pill-button')]", # More specific XPath
                "[data-control-name='filter_dateposted']",
                "button.artdeco-dropdown__trigger:has-text('Date posted')", # Old selector
            ]
            
            date_filter_button_clicked = False
            for i, selector in enumerate(date_filter_button_selectors):
                try:
                    print(f"Attempting selector {i+1}/{len(date_filter_button_selectors)} for 'Date posted' button: {selector}")
                    if selector.startswith("//"):
                        date_filter_trigger = self.wait.until(EC.element_to_be_clickable((By.XPATH, selector)))
                    else:
                        date_filter_trigger = self.wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, selector)))
                    
                    print(f"Element found with selector: {selector}. Scrolling into view...")
                    self.driver.execute_script("arguments[0].scrollIntoView(true);", date_filter_trigger)
                    self._random_delay(0.5,1)
                    print(f"Clicking 'Date posted' filter button using selector: {selector}")
                    date_filter_trigger.click()
                    date_filter_button_clicked = True
                    print(f"Successfully clicked 'Date posted' filter button using selector: {selector}")
                    self._random_delay(1, 2) # Wait for dropdown to open
                    break
                except (TimeoutException, NoSuchElementException, StaleElementReferenceException) as ex_button:
                    print(f"Selector {selector} for 'Date posted' button failed: {ex_button}. Trying next.")
                    continue
            
            if not date_filter_button_clicked:
                print("Could not find or click the 'Date posted' filter button after trying all selectors.")
                return

            # Map user-friendly filter names to the 'id' of the radio input
            print("Mapping date filter option to ID...")
            date_option_ids = {
                "Any time": "timePostedRange-", 
                "Past 24 hours": "timePostedRange-r86400",
                "Past week": "timePostedRange-r604800",
                "Past month": "timePostedRange-r2592000"
            }
            target_option_id = date_option_ids.get(date_filter)

            if not target_option_id:
                print(f"Unknown date filter option: {date_filter}. Available: {list(date_option_ids.keys())}")
                try:
                    # Attempt to close the dropdown if an unknown option is provided
                    # This might involve clicking a cancel button or pressing Escape
                    # For now, just log and return
                    print("Attempting to close date filter dropdown due to unknown option.")
                    # Example: self.driver.find_element(By.XPATH, "//button[contains(@aria-label, 'Cancel')]").click()
                    # Or: from selenium.webdriver.common.action_chains import ActionChains
                    # ActionChains(self.driver).send_keys(Keys.ESCAPE).perform()
                except Exception as close_ex:
                    print(f"Could not close dropdown: {close_ex}")
                return

            print(f"Target option ID: {target_option_id}. Attempting to select it...")
            # Find and click the label associated with the target radio input
            try:
                label_selector = f"label[for='{target_option_id}']"
                print(f"Waiting for label with selector: {label_selector}")
                option_label = self.wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, label_selector)))
                
                print("Label found. Scrolling into view and clicking...")
                self.driver.execute_script("arguments[0].scrollIntoView(true);", option_label) 
                self._random_delay(0.5, 1)
                option_label.click()
                print(f"Selected date filter option: '{date_filter}' (label for '{target_option_id}')")
                self._random_delay(0.5, 1)

                # Click the "Show results" button to apply the filter
                print("Attempting to click 'Show results' / 'Apply' button...")
                apply_button_selectors = [
                    "//div[contains(@class, 'reusable-search-filters-buttons')]//button[contains(@class, 'artdeco-button--primary') and (contains(., 'Show results') or contains(., 'Apply'))]",
                    "button[aria-label='Apply current filter to show results']",
                    "button.filters-button-bottom-sheet__submit-button" # A common pattern for mobile/responsive views or new UI
                ]
                apply_clicked = False
                for i, apply_selector in enumerate(apply_button_selectors):
                    try:
                        print(f"Attempting selector {i+1}/{len(apply_button_selectors)} for 'Apply' button: {apply_selector}")
                        if apply_selector.startswith("//"):
                             apply_filter_button = self.wait.until(EC.element_to_be_clickable((By.XPATH, apply_selector)))
                        else:
                            apply_filter_button = self.wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, apply_selector)))
                        print(f"Apply button found with selector: {apply_selector}. Clicking...")
                        apply_filter_button.click()
                        apply_clicked = True
                        print("Clicked 'Show results' / 'Apply' button to apply date filter.")
                        self._random_delay(2, 4) # Wait for results to reload
                        break
                    except (TimeoutException, NoSuchElementException, StaleElementReferenceException) as ex_apply:
                        print(f"Apply button selector {apply_selector} failed: {ex_apply}. Trying next.")
                        continue
                
                if not apply_clicked:
                    print("Could not click 'Show results' / 'Apply' button after trying all selectors.")

            except (TimeoutException, NoSuchElementException) as ex_label:
                print(f"Could not find or click label for date filter option: {date_filter} (ID: {target_option_id}). Error: {ex_label}")
            
        except Exception as e:
            print(f"Error applying date filter at a higher level: {e}")
            # It's often better to continue without the filter than to fail the whole search
    
    def _collect_job_urls_on_page(self, limit=float('inf')):
        """Collect all job URLs from the current page of search results."""
        try:
            # First make sure the page is fully loaded
            print("Waiting for job search results to load...")
            # Try to find the main list container for jobs
            list_container_selectors = [
                "ul.semantic-search-results-list", # From provided HTML
                "div.jobs-search-results-list", 
                ".jobs-search__results-list", # General class for job results container
                "div.scaffold-layout__list-detail-inner ul" # More generic
            ]
            job_list_container_element = None
            for lc_selector in list_container_selectors:
                try:
                    job_list_container_element = self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, lc_selector)))
                    print(f"Found job list container with selector: {lc_selector}")
                    self._random_delay(1, 2)
                    break
                except TimeoutException:
                    print(f"Job list container selector {lc_selector} not found.")
                    continue
            
            if not job_list_container_element:
                print("Primary job list container not found with any selector. Attempting fallback to find job cards directly.")
                # Fallback logic for job cards will run if container isn't found for scrolling.

            # Try multiple selectors for job cards, prioritizing specific ones from HTML
            job_card_selectors = [
                "li.semantic-search-results-list__list-item", # From provided HTML
                "div.job-card-job-posting-card-wrapper", # From provided HTML (often child of li)
                "div.job-card-container", # Older selector
                "li.jobs-search-results__list-item", # Older selector
                "li.scaffold-layout__list-item", # General layout item
                ".job-search-card" # Generic card
            ]
            
            job_cards = []
            # Try to find job cards using different selectors within the identified container or page
            # If job_list_container_element is found, search within it, else search whole driver.
            search_context = job_list_container_element if job_list_container_element else self.driver

            for selector in job_card_selectors:
                try:
                    # Wait for job cards to appear with this selector
                    self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, selector)))
                    job_cards = self.driver.find_elements(By.CSS_SELECTOR, selector)
                    if job_cards:
                        print(f"Found {len(job_cards)} job cards with selector: {selector}")
                        break
                except (TimeoutException, NoSuchElementException):
                    continue
            
            if not job_cards:
                print("No job cards found with any selector")
                # As a fallback, try to find any elements that might contain job links
                try:
                    print("Trying fallback method to find job links directly")
                    # Look for any links that contain '/jobs/view/'
                    job_links = self.driver.find_elements(
                        By.XPATH, "//a[contains(@href, '/jobs/view/')]"
                    )
                    for link in job_links:
                        try:
                            href = link.get_attribute("href")
                            if href and "/jobs/view/" in href:
                                job_id = href.split("/jobs/view/")[1].split("/")[0].split("?")[0]
                                clean_url = f"https://www.linkedin.com/jobs/view/{job_id}"
                                self.job_urls.add(clean_url)
                                print(f"Added job URL via fallback: {clean_url}")
                        except StaleElementReferenceException:
                            continue
                except Exception as e:
                    print(f"Fallback method failed: {e}")
                return len(self.job_urls) > 0
            
            # Find the scrollable job list container (already attempted with job_list_container_element)
            # If job_list_container_element was found, use it for scrolling.
            if job_list_container_element:
                print("Scrolling through job list to load all results")
                try:
                    # Scroll down in small increments to load all results
                    last_height = self.driver.execute_script("return arguments[0].scrollHeight", job_list_container_element)
                    
                    # Perform initial scroll to trigger lazy loading
                    self.driver.execute_script("arguments[0].scrollTop = 0", job_list_container_element)
                    self._random_delay(1, 2)
                    
                    scroll_attempts = 0
                    max_scroll_attempts = 5
                    while scroll_attempts < max_scroll_attempts:
                        scroll_attempts += 1
                        
                        # Scroll down incrementally
                        for i in range(1, 6):  # Reduced from 10 to 5 steps
                            scroll_amount = i * last_height / 5
                            self.driver.execute_script(f"arguments[0].scrollTop = {scroll_amount}", job_list_container_element)
                            self._random_delay(0.3, 0.6)  # Slightly longer delays
                        
                        # Wait for more results to load
                        self._random_delay(1.5, 2.5)
                        
                        # Calculate new scroll height and compare with last scroll height
                        new_height = self.driver.execute_script("return arguments[0].scrollHeight", job_list_container_element)
                        if new_height == last_height:
                            break
                        last_height = new_height
                        
                        # Try to get updated job cards after scrolling
                        try:
                            # Re-query job cards within the container after scroll
                            current_card_selector = ""
                            for s_check in job_card_selectors: # Find which selector is working
                                if search_context.find_elements(By.CSS_SELECTOR, s_check):
                                    current_card_selector = s_check
                                    break
                            if current_card_selector:
                                fresh_cards = search_context.find_elements(By.CSS_SELECTOR, current_card_selector)
                                if fresh_cards and len(fresh_cards) > len(job_cards):
                                    job_cards = fresh_cards # Update with newly loaded cards
                                    print(f"Found {len(job_cards)} job cards after scrolling")
                        except StaleElementReferenceException:
                            print("Stale element reference during scroll, attempting to re-find cards.")
                            # Re-find cards on the whole page as a fallback
                            for s_check in job_card_selectors:
                                try:
                                    job_cards = self.driver.find_elements(By.CSS_SELECTOR, s_check)
                                    if job_cards: break
                                except: continue
                            print(f"Refreshed job cards, found {len(job_cards)}")
                            # Update last_height from the main driver if container became stale
                            last_height = self.driver.execute_script("return document.body.scrollHeight")


                except Exception as e:
                    print(f"Error during scrolling: {e}")
            else:
                print("Scrollable job list container not identified; proceeding without scrolling through list.")

            # Extract job links from all cards
            print(f"Extracting URLs from {len(job_cards)} job cards")
            # The user's XPath /html/body/div[6]/div[3]/div[3]/div/div[2]/main/div/div[2]/div[1]/ul/li[2]/div/a
            # indicates the 'a' tag is often a child of a 'div' within the 'li' (card).
            # Let's try a direct 'a' selector first, as it's common for the main link.
            # Then, a more specific one if needed, and fallbacks.
            link_selectors = [
                "a",                                                  # Most generic: find any 'a' tag in the card
                "div > a",                                            # 'a' tag that is a direct child of a 'div' in the card
                ".job-card-container__link",                          # An older specific class
                "a.job-card-list__title",                             # Another older specific class
                "a[data-control-name='job_card_title']",              # Data attribute
                "a.job-search-card__link",                            # Generic search card link
                "a.job-card-job-posting-card-wrapper__card-link"      # The one that found a search-results link
            ]
            
            cards_processed = 0
            # The 'limit' parameter here is effective_max_links from search_jobs, currently 25.
            # If we want to collect ALL links from the page, this check needs to be removed or the limit passed as float('inf').
            # For now, let's remove this specific check here, as the main control is pages_to_scan.
            # The overall total limit is handled in main.py.
            for idx, card in enumerate(job_cards):
                cards_processed += 1
                if cards_processed % 5 == 0 or cards_processed == 1 or cards_processed == len(job_cards) : # Log first, last, and every 5th
                    print(f"Processing card {cards_processed}/{len(job_cards)}")
                
                # Removed: if len(self.job_urls) >= limit: ... break
                
                link_found_in_card = False
                # Try multiple link selectors for each card
                for i_ls, link_selector in enumerate(link_selectors):
                    if cards_processed == 1: # Log selectors only for the first card to avoid excessive logging
                        print(f"  Card {cards_processed}: Trying link selector {i_ls+1}/{len(link_selectors)}: {link_selector}")
                    try:
                        # Ensure card is a WebElement, not a string or other type
                        if not hasattr(card, 'find_elements'):
                            if cards_processed == 1: print(f"  Card {cards_processed}: Item is not a WebElement. Skipping selector.")
                            continue

                        anchors = card.find_elements(By.CSS_SELECTOR, link_selector)
                        if anchors:
                            if cards_processed == 1: print(f"  Card {cards_processed}: Found {len(anchors)} anchor(s) with selector {link_selector}")
                            
                            # Iterate through all found anchors by a selector, in case the first isn't the one we want
                            for anchor_idx, anchor in enumerate(anchors):
                                href = anchor.get_attribute("href")
                                if cards_processed == 1: print(f"  Card {cards_processed}, Anchor {anchor_idx+1}: Href: {href}")

                                if href:
                                    # Priority 1: Direct /jobs/view/ link
                                    if "/jobs/view/" in href:
                                        job_id_match = href.split("/jobs/view/")
                                        if len(job_id_match) > 1:
                                            job_id = job_id_match[1].split("/")[0].split("?")[0]
                                            clean_url = f"https://www.linkedin.com/jobs/view/{job_id}"
                                            if clean_url not in self.job_urls:
                                                self.job_urls.add(clean_url)
                                                print(f"  Card {cards_processed}: Added job URL (from /jobs/view/): {clean_url} (Total: {len(self.job_urls)})")
                                            elif cards_processed == 1:
                                                print(f"  Card {cards_processed}: URL {clean_url} already collected.")
                                            link_found_in_card = True
                                            break # Found a valid link for this card from this anchor
                                        elif cards_processed == 1:
                                            print(f"  Card {cards_processed}, Anchor {anchor_idx+1}: Href '{href}' has /jobs/view/ but invalid structure after.")
                                    
                                    # Priority 2: Link with currentJobId=
                                    elif "currentJobId=" in href:
                                        try:
                                            # Extract job ID from currentJobId query parameter
                                            parsed_url = urllib.parse.urlparse(href)
                                            query_params = urllib.parse.parse_qs(parsed_url.query)
                                            if 'currentJobId' in query_params and query_params['currentJobId']:
                                                job_id = query_params['currentJobId'][0]
                                                clean_url = f"https://www.linkedin.com/jobs/view/{job_id}"
                                                if clean_url not in self.job_urls:
                                                    self.job_urls.add(clean_url)
                                                    print(f"  Card {cards_processed}: Added job URL (from currentJobId): {clean_url} (Total: {len(self.job_urls)})")
                                                elif cards_processed == 1:
                                                    print(f"  Card {cards_processed}: URL {clean_url} (from currentJobId) already collected.")
                                                link_found_in_card = True
                                                break # Found a valid link for this card from this anchor
                                            elif cards_processed == 1:
                                                print(f"  Card {cards_processed}, Anchor {anchor_idx+1}: Href '{href}' has currentJobId but no value.")
                                        except Exception as e_parse:
                                            if cards_processed == 1: print(f"  Card {cards_processed}, Anchor {anchor_idx+1}: Error parsing currentJobId from '{href}': {e_parse}")
                                    
                                    elif cards_processed == 1:
                                        print(f"  Card {cards_processed}, Anchor {anchor_idx+1}: Href '{href}' does not contain '/jobs/view/' or 'currentJobId='.")
                                else: # href is None
                                     if cards_processed == 1: print(f"  Card {cards_processed}, Anchor {anchor_idx+1}: Href is None.")
                                
                                if link_found_in_card: # If a link was found from any anchor from this selector
                                    break
                            # End of loop through anchors from one selector
                        elif cards_processed == 1:
                             print(f"  Card {cards_processed}: No anchors found with selector {link_selector}")
                    except StaleElementReferenceException:
                        if cards_processed == 1: print(f"  Card {cards_processed}: StaleElementReferenceException for selector {link_selector}")
                        break # Break from link_selectors loop for this card, move to next card
                    except Exception as e_link:
                        if cards_processed == 1: print(f"  Card {cards_processed}: Error with link selector {link_selector}: {e_link}")
                        # Continue to the next selector for this card
                
                if link_found_in_card: # If a link was found from any selector for this card
                    continue # Move to the next card

                # If no link found with CSS selectors, try direct data attribute on the card itself
                if cards_processed == 1: print(f"  Card {cards_processed}: Trying to get 'data-job-id' attribute from card.")
                try:
                    if not hasattr(card, 'get_attribute'):
                        if cards_processed == 1: print(f"  Card {cards_processed}: Item is not a WebElement for data-job-id. Skipping.")
                        continue # To the next card

                    job_id_attr = card.get_attribute("data-job-id")
                    if job_id_attr:
                        if cards_processed == 1: print(f"  Card {cards_processed}: Found data-job-id: {job_id_attr}")
                        clean_url = f"https://www.linkedin.com/jobs/view/{job_id_attr}"
                        if clean_url not in self.job_urls:
                            self.job_urls.add(clean_url)
                            print(f"  Card {cards_processed}: Added job URL from data-job-id: {clean_url} (Total: {len(self.job_urls)})")
                        elif cards_processed == 1:
                            print(f"  Card {cards_processed}: URL {clean_url} (from data-job-id) already collected.")
                        # link_found_in_card = True # Not strictly needed here as it's the last resort for the card
                    elif cards_processed == 1:
                        print(f"  Card {cards_processed}: 'data-job-id' attribute not found or is empty.")
                except StaleElementReferenceException:
                    if cards_processed == 1: print(f"  Card {cards_processed}: StaleElementReferenceException for data-job-id.")
                except Exception as e_attr: # Catch any other error during get_attribute
                    if cards_processed == 1: print(f"  Card {cards_processed}: Error extracting 'data-job-id': {e_attr}")
            
            print(f"Finished processing all cards. Total unique job URLs collected: {len(self.job_urls)}")
            return True
        
        except Exception as e:
            print(f"Error collecting job URLs: {e}")
            return False
    
    def _go_to_next_page(self):
        """Try to navigate to the next page of search results with enhanced logging."""
        logger.info("Attempting to go to the next page...")
        next_button_found_and_clicked = False
        try:
            # More robust selectors, including those observed in debug HTML
            next_selectors = [
                "button[aria-label='View next page']", # From debugged HTML May 2025
                "//button[@aria-label='Next']", # Specific to "Next" button often seen
                "//button[contains(text(), 'Next') and not(@disabled)]", # Text based, not disabled
                "button[aria-label='Load more results']", # Common for infinite scroll type pages
                "button.jobs-search-results-list__show-more-button", # Older selector
                "button.infinite-scroller__show-more-button", # Older selector for infinite scroll
                "button.artdeco-pagination__button--next" # Generic Art Deco next button
            ]

            for i, sel in enumerate(next_selectors):
                logger.info(f"  Trying selector {i+1}/{len(next_selectors)}: {sel}")
                try:
                    # Wait for the button to be present first
                    WebDriverWait(self.driver, 5).until(
                        EC.presence_of_element_located((By.XPATH if sel.startswith("//") else By.CSS_SELECTOR, sel))
                    )
                    btns = self.driver.find_elements(By.XPATH if sel.startswith("//") else By.CSS_SELECTOR, sel)
                    
                    if not btns:
                        logger.info(f"    Selector {sel} found no elements.")
                        continue

                    for btn_idx, btn in enumerate(btns):
                        logger.info(f"    Found potential button {btn_idx+1} with selector {sel}.")
                        try:
                            btn_html = btn.get_attribute('outerHTML')
                            logger.info(f"      Button HTML: {btn_html[:200]}...") # Log first 200 chars
                            is_disp = btn.is_displayed()
                            is_enb = btn.is_enabled()
                            logger.info(f"      Is Displayed: {is_disp}, Is Enabled: {is_enb}")

                            if is_disp and is_enb:
                                logger.info(f"      Attempting to scroll button into view and click (standard).")
                                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", btn)
                                self._random_delay(0.7, 1.2)
                                # WebDriverWait(self.driver, 5).until(EC.element_to_be_clickable(btn)) # Ensure clickable
                                btn.click()
                                logger.info(f"      Successfully clicked 'Next' button using selector: {sel}")
                                self._random_delay(3, 6)  # Wait for next page to load
                                next_button_found_and_clicked = True
                                return True # Exit after successful click
                        except StaleElementReferenceException:
                            logger.warning(f"      StaleElementReferenceException for button with selector {sel}. Re-finding.")
                            break # Break inner loop to re-evaluate selectors on fresh DOM
                        except Exception as e_click:
                            logger.warning(f"      Could not click button with selector {sel} using standard click: {e_click}")
                            # Try JavaScript click as a fallback
                            try:
                                logger.info(f"      Attempting JavaScript click for button with selector {sel}.")
                                self.driver.execute_script("arguments[0].click();", btn)
                                logger.info(f"      Successfully clicked 'Next' button using JavaScript with selector: {sel}")
                                self._random_delay(3, 6)
                                next_button_found_and_clicked = True
                                return True
                            except Exception as e_js_click:
                                logger.error(f"      JavaScript click also failed for selector {sel}: {e_js_click}")
                                continue # Try next button if multiple were found by this selector
                    if next_button_found_and_clicked: # Should have returned True already
                        break 
                except TimeoutException:
                    logger.info(f"    Selector {sel} timed out (element not present or not clickable quickly enough).")
                    continue # Try next selector
                except NoSuchElementException:
                    logger.info(f"    Selector {sel} found no elements (NoSuchElementException).")
                    continue # Try next selector
                except Exception as e_sel:
                    logger.error(f"    Unexpected error with selector {sel}: {e_sel}")
                    continue

            if not next_button_found_and_clicked:
                logger.warning("No 'Next' button was successfully clicked after trying all selectors.")
                # Save page source if pagination fails
                try:
                    timestamp = time.strftime("%Y%m%d-%H%M%S")
                    results_dir_path = getattr(self, 'results_dir', '.')
                    if not os.path.isdir(results_dir_path):
                        try:
                            os.makedirs(results_dir_path, exist_ok=True)
                        except OSError: # e.g. permission error
                            logger.warning(f"Could not create results_dir {results_dir_path}, falling back to current dir.")
                            results_dir_path = "." 
                    debug_html_path = os.path.join(results_dir_path, f"debug_pagination_fail_{timestamp}.html")
                    with open(debug_html_path, 'w', encoding='utf-8') as f:
                        f.write(self.driver.page_source)
                    logger.info(f"Saved page source for pagination failure to {debug_html_path}")
                except Exception as e_save:
                    logger.error(f"Error saving debug page source on pagination failure: {e_save}")
                return False

        except Exception as e:
            logger.error(f"Error navigating to next page: {e}", exc_info=True)
            return False
        # Fallback return, though ideally one of the returns inside the loop or after selectors should hit.
        return False
