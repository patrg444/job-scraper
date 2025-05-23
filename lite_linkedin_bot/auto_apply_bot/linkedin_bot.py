import time
import csv
import random
import re
import os
import sys
import logging
from typing import Dict, Any
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, WebDriverException, StaleElementReferenceException, ElementClickInterceptedException
from selenium.webdriver.support.ui import Select
from webdriver_manager.chrome import ChromeDriverManager
from .resume_parser import ResumeParser 
try:
    from .resume_parser import SKILL_RELATIONSHIPS
except ImportError:
    SKILL_RELATIONSHIPS = {} 
from .job_parser import parse_job_description 
from .form_handler import FormHandler 

try:
    import openai 
    from openai import OpenAI 
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False
    try:
        logger_init_fail = logging.getLogger(__name__)
        logger_init_fail.warning("OpenAI library is not installed or OpenAI client class could not be imported. LLM features will be disabled.")
    except Exception:
        print("CRITICAL: OpenAI library import failed AND logging couldn't be initialized at that point.")

logger = logging.getLogger(__name__)

from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.common.keys import Keys 

# Generic anchor to find any H1, H2, H3 or H4 within the modal content that has text
STEP_ANCHORS = (
    (By.XPATH, "//div[contains(@class,'jobs-easy-apply-modal__content')]//*[self::h1 or self::h2 or self::h3 or self::h4][normalize-space()]"),
)

class safe_url_contains:
    def __init__(self, substring):
        self.substring = substring

    def __call__(self, driver):
        try:
            current_url = driver.current_url
            if current_url is None:
                logger.debug("safe_url_contains: driver.current_url is None, returning False.")
                return False
            return self.substring in current_url
        except WebDriverException as e: 
            logger.warning(f"safe_url_contains: WebDriverException ({e}) while getting current_url, returning False.")
            return False

class EasyApplyBot:
    def __init__(self, email, password, resume_path, form_answers=None, openai_api_key=None, use_llm=False, results_dir=".", skip_if_applied_override=True): 
        self.email = email
        self.password = password
        self.resume_path = resume_path
        self.skip_if_applied_override = skip_if_applied_override 
        self.driver = None
        self.wait = None 
        self.short_wait = None 
        self.current_job_data = {}
        self.use_llm = use_llm
        self.openai_client = None
        self.results_dir = results_dir 
        self.form_handler = None
        self._last_anchor_text = None # Cache for generic step anchor
        self._last_progress_value = None # Cache for progress bar value
        self.current_job_url_for_debug = "" # For debug filenames

        if self.use_llm and OPENAI_AVAILABLE:
            if openai_api_key:
                try:
                    self.openai_client = OpenAI(api_key=openai_api_key)
                    logger.info("OpenAI client initialized and API key set. LLM use effectively enabled.")
                except Exception as e:
                    logger.error(f"Failed to initialize OpenAI client: {e}. LLM features will be disabled.")
                    self.use_llm = False
            else:
                logger.warning("LLM use was configured as True, but no OpenAI API key was provided. LLM features will be disabled.")
                self.use_llm = False
        elif self.use_llm and not OPENAI_AVAILABLE:
            logger.warning("LLM use was configured as True, but OpenAI library is not available. LLM features will be disabled.")
            self.use_llm = False
        else:
            if not self.use_llm:
                 logger.info("LLM use is disabled by configuration.")
            self.use_llm = False
        
        self.form_answers = form_answers or {
            "default_dropdown": "Yes", "default_text": "N/A", "dropdown_map": {},
            "text_map": {}, "company_specific": {}, "experience_yes_keywords": []
        }
        try:
            parser = ResumeParser(resume_path)
            self.resume_data = parser.parse()
            logger.info(f"Successfully parsed resume from {resume_path}")
        except Exception as e:
            logger.error(f"Failed to parse resume: {e}")
            self.resume_data = {
                "first_name": "", "last_name": "", "full_name": "", "email": email, "phone": "",
                "address": "", "city": "", "state": "", "zip": "", "country": "United States",
                "years_experience": None, "education_level": "Bachelor's Degree",
                "certifications": [], "languages": [], "skills": [], "project_roles": [], "work_experiences": []
            }

    def _init_driver(self):
        try:
            options = webdriver.ChromeOptions()
            options.add_argument("--disable-blink-features=AutomationControlled")
            options.add_experimental_option("excludeSwitches", ["enable-automation"])
            options.add_experimental_option('useAutomationExtension', False)
            options.add_argument("--start-maximized")
            options.add_argument('--no-sandbox') 
            options.add_argument('--disable-dev-shm-usage') 
            options.add_argument(f'--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36')

            self.driver = webdriver.Chrome(ChromeDriverManager().install(), options=options)
            self.driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
                "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            })
            self.wait = WebDriverWait(self.driver, 20) 
            self.short_wait = WebDriverWait(self.driver, 3) # Short wait for quick checks like staleness
            self.form_handler = FormHandler(self.driver, self.wait, self.short_wait, self)
            print("WebDriver initialized successfully.")
        except WebDriverException as e:
            print(f"Error initializing WebDriver: {e}"); self.driver = None; raise 

    def login(self):
        if not self.driver: print("Driver not initialized."); return False
        print("Attempting to log in to LinkedIn...")
        try:
            self.driver.delete_all_cookies(); self.driver.get("https://www.linkedin.com/login"); time.sleep(random.uniform(2,4))
            self._type_slowly(self.wait.until(EC.presence_of_element_located((By.ID, "username"))), self.email)
            self._type_slowly(self.driver.find_element(By.ID, "password"), self.password)
            time.sleep(random.uniform(0.5, 1.5)); self.driver.find_element(By.CSS_SELECTOR, "button[type=submit]").click()
            
            WebDriverWait(self.driver, 25).until(
                EC.any_of(
                    safe_url_contains("linkedin.com/feed"), 
                    safe_url_contains("linkedin.com/jobs"),  
                    EC.presence_of_element_located((By.ID, "global-nav-search")) 
                )
            )
            current_url = self.driver.current_url 
            logger.info(f"After WebDriverWait, current URL is: {current_url}")

            url_is_feed = current_url and "linkedin.com/feed" in current_url
            url_is_jobs = current_url and "linkedin.com/jobs" in current_url
            global_nav_present = bool(self.driver.find_elements(By.ID, "global-nav-search")) 

            if url_is_feed or url_is_jobs or global_nav_present:
                print(f"Login successful. URL: {current_url}"); return True
            
            if current_url and ("checkpoint" in current_url or "challenge" in current_url):
                logger.warning(f"LinkedIn security checkpoint/challenge detected at URL: {current_url}")
                print(f"\nLinkedIn security checkpoint detected. URL: {current_url}")
                print("Please solve the CAPTCHA or verification in the browser window.")
                input("Press Enter in this console after you have successfully solved the checkpoint and landed on the main LinkedIn page (e.g., feed or jobs)...")
                
                current_url_after_manual = self.driver.current_url
                logger.info(f"URL after manual checkpoint solving attempt: {current_url_after_manual}")
                if current_url_after_manual and ("linkedin.com/feed" in current_url_after_manual or "linkedin.com/jobs" in current_url_after_manual):
                    print(f"Login successful after manual intervention. URL: {current_url_after_manual}")
                    return True
                else:
                    print(f"Login still not successful after manual intervention. Current URL: {current_url_after_manual}")
                    return False

            print(f"Still on login page or unexpected page after initial checks. URL: {current_url}"); return False
        except TimeoutException:
            current_url_on_timeout = self.driver.current_url
            logger.error(f"Timeout waiting for login confirmation. Current URL: {current_url_on_timeout}")
            
            if current_url_on_timeout and ("checkpoint" in current_url_on_timeout or "challenge" in current_url_on_timeout):
                print(f"\nLinkedIn security checkpoint detected (on timeout). URL: {current_url_on_timeout}")
                print("Please solve the CAPTCHA or verification in the browser window.")
                input("Press Enter in this console after you have successfully solved the checkpoint and landed on the main LinkedIn page (e.g., feed or jobs)...")
                
                current_url_after_manual = self.driver.current_url
                logger.info(f"URL after manual checkpoint solving attempt (on timeout): {current_url_after_manual}")
                if current_url_after_manual and ("linkedin.com/feed" in current_url_after_manual or "linkedin.com/jobs" in current_url_after_manual):
                    print(f"Login successful after manual intervention (on timeout). URL: {current_url_after_manual}")
                    return True
                else:
                    print(f"Login still not successful after manual intervention (on timeout). Current URL: {current_url_after_manual}")
                    return False
            else: 
                print(f"Login timed out and not on a clear checkpoint page. Current URL: {current_url_on_timeout}")
                return False
        except Exception as e: 
            print(f"Login error: {e}"); return False

    def _type_slowly(self, element, text):
        for char in text: element.send_keys(char); time.sleep(random.uniform(0.05, 0.15))

    def _scroll_job_panel(self):
        try:
            panel_selectors = ["div.jobs-search-results-list", "div.jobs-details__main-content", "div.job-view-layout__inner", "main[aria-label='Job details']"]
            panel_to_scroll = next((self.driver.find_element(By.CSS_SELECTOR, s) for s in panel_selectors if self.driver.find_elements(By.CSS_SELECTOR, s) and self.driver.find_element(By.CSS_SELECTOR, s).is_displayed()), None)
            if panel_to_scroll: self.driver.execute_script("arguments[0].scrollTop += 300;", panel_to_scroll); logger.info("Scrolled job panel.")
            else: self.driver.execute_script("window.scrollBy(0, 250);"); logger.info("Scrolled window as fallback.")
            time.sleep(0.5)
        except Exception as e: logger.warning(f"Job panel scroll error: {e}")

    def _get_text_if_present(self, by, value, default=""):
        try:
            element = self.driver.find_element(by, value)
            if element and element.is_displayed():
                text = element.text.strip()
                if text:
                    logger.debug(f"Found text '{text}' with selector {by} -> {value}")
                    return text
            logger.debug(f"Selector {by} -> {value} found no visible text or element.")
        except NoSuchElementException:
            logger.debug(f"Selector {by} -> {value} not found.")
            self._dump_dom_for_debug(failed_selector_tuple=(by, value), 
                                     failure_description="get_text_fail_no_such_el")
        except Exception as e:
            logger.warning(f"Error getting text for selector {by} -> {value}: {e}")
            # Consider what context selector might be useful here. Defaulting to body.
            self._dump_dom_for_debug(failed_selector_tuple=(by, value), 
                                     failure_description="get_text_fail_exception")
        return default

    def _get_job_title_from_top_card(self) -> str:
        selectors = [
            (By.CSS_SELECTOR, "div.job-details-jobs-unified-top-card__job-title > h1.t-24.t-bold.inline"), # Specific to TikTok-like HTML structure
            (By.CSS_SELECTOR, "div.job-details-jobs-unified-top-card__job-title > h1.t-24.t-bold"), # Fallback if 'inline' is not present
            (By.CSS_SELECTOR, "h1.t-24.t-bold.jobs-unified-top-card__job-title"), 
            (By.CSS_SELECTOR, "h1.jobs-unified-top-card__job-title"),
            (By.CSS_SELECTOR, "h1.topcard__title"),
            (By.XPATH, "//h1[contains(@class, 'job-title')] | //h1[contains(@class, 'job-details-jobs-unified-top-card__job-title')]")
        ]
        for by, sel in selectors:
            title = self._get_text_if_present(by, sel)
            if title: return title
        return ""

    def _get_company_name_from_top_card(self) -> str:
        selectors = [
            (By.CSS_SELECTOR, "div.job-details-jobs-unified-top-card__company-name > a"), # Matches TikTok HTML
            (By.CSS_SELECTOR, "span.jobs-unified-top-card__company-name > a"), 
            (By.CSS_SELECTOR, "span.jobs-unified-top-card__company-name"), 
            (By.CSS_SELECTOR, ".topcard__org-name-link"),
            (By.CSS_SELECTOR, "a[data-tracking-control-name='public_jobs_topcard_org_name']"),
            (By.XPATH, "//div[contains(@class, 'job-details-jobs-unified-top-card__primary-description-container')]//a[contains(@href, '/company/')]")
        ]
        for by, sel in selectors:
            name = self._get_text_if_present(by, sel)
            if name:
                # Basic cleaning, can be enhanced
                name_lower = name.lower()
                for suffix in [' inc.', ' llc', ' ltd.', ' corp.']: # Common suffixes
                    if name_lower.endswith(suffix):
                        name = name[:-len(suffix)].strip()
                        break
                return name
        return ""

    def _get_location_from_top_card(self) -> str:
        location_text = ""
        workplace_type = ""
        
        # Primary location text
        location_selectors = [
            # Specific for new structure like TikTok's "San Jose, CA"
            (By.CSS_SELECTOR, "div.job-details-jobs-unified-top-card__tertiary-description-container > span[dir='ltr'] > span.tvm__text:nth-child(1)"),
            (By.CSS_SELECTOR, "span.jobs-unified-top-card__location"), # Original specific selector
            # Fallback to bullet, but be cautious as it might pick up other info
            (By.CSS_SELECTOR, "span.jobs-unified-top-card__bullet"), 
            (By.XPATH, "//span[contains(@class, 'topcard__flavor--bullet') and not(contains(.,'employees')) and not(contains(.,'applicant')) and not(contains(.,'ago')) and not(contains(.,'Full-time')) and not(contains(.,'Part-time')) and not(contains(.,'Contract'))][1]")
        ]
        for by, sel in location_selectors:
            loc = self._get_text_if_present(by, sel)
            # Ensure the text found is likely a location and not something else
            if loc and not any(kw in loc.lower() for kw in ["applicant", "employee", "ago", "posted", "full-time", "part-time", "contract", "internship", "temporary", "remote", "hybrid", "on-site"]):
                location_text = loc.strip().split('·')[0].strip() 
                break
        
        # Workplace type (Remote, Hybrid, On-site)
        workplace_selectors = [
             # Specific for new structure like TikTok's "On-site" in a div
            (By.XPATH, "//div[contains(@class,'job-details-jobs-unified-top-card__job-insight') and (normalize-space(.)='On-site' or normalize-space(.)='Remote' or normalize-space(.)='Hybrid')]"),
            (By.CSS_SELECTOR, "span.jobs-unified-top-card__workplace-type"), # Original specific
            (By.XPATH, "//span[contains(@class, 'topcard__flavor--bullet') and (contains(.,'Remote') or contains(.,'Hybrid') or contains(.,'On-site'))]"), # Original bullet based
        ]
        for by, sel in workplace_selectors:
            wt = self._get_text_if_present(by, sel)
            if wt: # wt already comes from _get_text_if_present, so it's stripped
                if "remote" in wt.lower(): workplace_type = "Remote"
                elif "hybrid" in wt.lower(): workplace_type = "Hybrid"
                elif "on-site" in wt.lower() or "onsite" in wt.lower(): workplace_type = "On-site"
                break
        
        if location_text and workplace_type and workplace_type not in location_text:
            return f"{location_text} ({workplace_type})"
        elif location_text:
            return location_text
        elif workplace_type: # If only workplace type is found (e.g. "Remote")
            return workplace_type
        return ""

    def _get_employment_type_from_top_card(self) -> str:
        insight_selectors = [
            # Selector for pills like "Full-time", "On-site" in the new structure
            (By.XPATH, "//button[contains(@class,'job-details-preferences-and-skills')]//div[contains(@class,'job-details-preferences-and-skills__pill')]/span[@class='ui-label text-body-small']"),
            # Fallback to original insight selectors
            (By.XPATH, "//div[contains(@class,'job-details-jobs-unified-top-card__job-insight')]"),
            (By.CSS_SELECTOR, "li.jobs-unified-top-card__job-insight span:not(.jobs-unified-top-card__job-insight-bullet)")
        ]
        employment_keywords = ["full-time", "part-time", "contract", "temporary", "internship"]
        
        for by, sel in insight_selectors:
            try:
                elements = self.driver.find_elements(by, sel)
                for element in elements:
                    if element and element.is_displayed():
                        text = element.text.strip()
                        if text:
                            text_lower = text.lower()
                            for keyword in employment_keywords:
                                # Check if the entire text of the pill IS an employment keyword
                                if keyword == text_lower:
                                     logger.debug(f"Found employment type '{text.capitalize()}' with selector {by} -> {sel} for exact match text '{text}'")
                                     return text.capitalize()
                                # Fallback to check if keyword is IN text (e.g., "Full-time · Entry level")
                                elif keyword in text_lower:
                                    match = re.search(rf'\b({keyword})\b', text, re.IGNORECASE)
                                    if match:
                                        logger.debug(f"Found employment type '{match.group(1).capitalize()}' with selector {by} -> {sel} for partial match text '{text}'")
                                        return match.group(1).capitalize()
            except NoSuchElementException:
                logger.debug(f"Selector {by} -> {sel} not found for employment type.")
            except Exception as e:
                logger.warning(f"Error processing employment type for selector {by} -> {sel}: {e}")
        return ""


    def _click_element_robustly(self, element_to_click, description="element") -> "WebElement | None":
        original_element_or_locator = element_to_click
        clicked_element_obj = None 
        try:
            if isinstance(original_element_or_locator, tuple):
                try:
                    element_for_scroll_and_click = self.short_wait.until(EC.presence_of_element_located(original_element_or_locator))
                except TimeoutException:
                    logger.error(f"Element not found with locator {original_element_or_locator} for {description}.")
                    # Sanitize description for filename
                    sanitized_description = re.sub(r'[^a-zA-Z0-9_-]', '_', description)[:30]
                    self._dump_dom_for_debug(failed_selector_tuple=original_element_or_locator,
                                             failure_description=f"click_presence_fail_{sanitized_description}")
                    return None
            else: 
                element_for_scroll_and_click = original_element_or_locator
            try: 
                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center', inline: 'nearest'});", element_for_scroll_and_click)
                time.sleep(0.5) 
            except Exception as e_scroll:
                logger.warning(f"Could not scroll {description} (element: {element_for_scroll_and_click.tag_name if hasattr(element_for_scroll_and_click, 'tag_name') else 'N/A'}) into view: {e_scroll}. Click might fail.")
            try:
                logger.debug(f"Robust click: Attempting standard click for {description}")
                clickable_element = self.short_wait.until(EC.element_to_be_clickable(element_for_scroll_and_click))
                clickable_element.click()
                logger.info(f"Clicked {description} (standard) successfully.")
                clicked_element_obj = clickable_element
                return clicked_element_obj
            except (TimeoutException, ElementClickInterceptedException, StaleElementReferenceException) as e_std:
                logger.warning(f"Standard click for {description} failed ({type(e_std).__name__}). Attempting JavaScript click.")
            except Exception as e_other_std: 
                logger.error(f"Unexpected error during standard click for {description}: {e_other_std}. Attempting JavaScript click.")
            try: 
                logger.debug(f"Robust click: Attempting JavaScript click for {description}")
                el_for_js = element_for_scroll_and_click 
                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center', inline: 'nearest'});", el_for_js)
                time.sleep(0.2) 
                self.driver.execute_script("arguments[0].click();", el_for_js)
                logger.info(f"Successfully clicked {description} using JavaScript.")
                clicked_element_obj = el_for_js
                return clicked_element_obj
            except Exception as e_js:
                logger.error(f"JavaScript click for {description} also failed: {e_js}", exc_info=True)
                return None
        except Exception as e_robust_outer: 
             logger.error(f"Outer error in robust click process for {description}: {e_robust_outer}", exc_info=True)
             return None

    def _parse_job_description(self):
        # self.current_job_data is assumed to be pre-populated with top-card data by the caller (e.g., collect_job_details)
        # This method will attempt to find description_text and use it to UPDATE self.current_job_data.
        description_text = ""
        logger.info("Attempting to parse job description (wrapper)...")
        try:
            # Attempt to click all "see more" type buttons to expand content
            # Common selectors for "see more" buttons in job descriptions
            see_more_button_css_selectors = [
                "button.jobs-description__footer-button",    # General "see more" in description footer
                "button.show-more-less-html__button--more",  # Common for expandable text sections
                "button[aria-expanded='false'].show-more-less-html__button", # More specific for unexpanded sections
                "button.jobs-description-see-more-button" # Another possible selector
            ]
            
            # Loop a few times to catch buttons that might appear after an initial expansion
            for _ in range(3): # Try up to 3 passes for clicking "see more" buttons
                buttons_clicked_in_pass = 0
                for selector in see_more_button_css_selectors:
                    try:
                        # Find all elements matching the selector
                        buttons = self.driver.find_elements(By.CSS_SELECTOR, selector)
                        for button in buttons:
                            if button.is_displayed() and button.is_enabled():
                                try:
                                    self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", button)
                                    time.sleep(0.3) # Brief pause for scroll
                                    self.driver.execute_script("arguments[0].click();", button)
                                    logger.info(f"Clicked a 'see more' button with selector: {selector}")
                                    buttons_clicked_in_pass += 1
                                    time.sleep(1.5) # Wait longer after a click for content to potentially load
                                except Exception as e_click:
                                    logger.debug(f"Could not click 'see more' button ({selector}): {e_click}")
                    except NoSuchElementException:
                        logger.debug(f"'See more' button selector not found: {selector}")
                    except Exception as e_find:
                        logger.warning(f"Error finding 'see more' buttons with selector {selector}: {e_find}")
                
                if buttons_clicked_in_pass == 0: # If no buttons were clicked in a full pass, assume all are expanded
                    logger.info("No more 'see more' buttons found or clicked in this pass.")
                    break
                else:
                    logger.info(f"Clicked {buttons_clicked_in_pass} 'see more' button(s) in this pass. Re-checking.")

            # Attempt to get the most specific full description container first
            primary_desc_selector = "div.jobs-description-content__text--stretch#job-details" 
            try:
                desc_element = self.driver.find_element(By.CSS_SELECTOR, primary_desc_selector)
                if desc_element.is_displayed():
                    description_text = desc_element.text.strip()
                    logger.info(f"Found description using primary selector: {primary_desc_selector}")
            except NoSuchElementException:
                logger.info(f"Primary description selector '{primary_desc_selector}' not found. Falling back to general selectors.")
            except Exception as e_primary_desc:
                logger.warning(f"Error trying primary description selector '{primary_desc_selector}': {e_primary_desc}")

            if not description_text: # If primary selector failed or element not displayed
                logger.info("Attempting fallback selectors for job description.")
                fallback_selectors_str = (
                    "div.jobs-description__content div.show-more-less-html__markup, "
                    "section[aria-label*='job details'] div[id*='description'] div.show-more-less-html__markup, "
                    ".show-more-less-html__markup, .description__text, .job-description, div#job-details"
                )
                desc_elements = []
                try:
                    desc_elements = self.driver.find_elements(By.CSS_SELECTOR, fallback_selectors_str)
                except Exception as e_fallback_find:
                    logger.error(f"Error finding elements with fallback selectors: {e_fallback_find}")

                if desc_elements:
                    largest_text_block = ""
                    selected_el_text = ""
                    for el_idx, el in enumerate(desc_elements):
                        try:
                            if el.is_displayed():
                                current_el_text = el.text.strip()
                                if len(current_el_text) > len(largest_text_block):
                                    largest_text_block = current_el_text
                                    selected_el_text = f"Fallback selector index {el_idx} (text length: {len(current_el_text)})"
                        except StaleElementReferenceException:
                            logger.debug(f"Stale element encountered in fallback description search at index {el_idx}. Skipping.")
                            continue
                        except Exception as e_el_proc:
                            logger.warning(f"Error processing element in fallback description search at index {el_idx}: {e_el_proc}")
                            continue
                    
                    if largest_text_block:
                        description_text = largest_text_block
                        logger.info(f"Found description using fallback selectors. Selected: {selected_el_text}")
                    else:
                        logger.warning("Fallback selectors found elements, but none were displayed or had processable text.")
                else:
                    logger.warning("No description elements found with fallback selectors either.")
            
            if description_text:
                parsed_data_from_description = parse_job_description(description_text) # from job_parser.py
                logger.info(f"Job description parsed. Data from description: {str(parsed_data_from_description)[:100]}...")

                # Merge parsed_data_from_description into self.current_job_data
                # The JobDescriptionParser already handles merging initial_facts (top-card data)
                # with data parsed from the description. The result (parsed_data_from_description)
                # is the consolidated view. So, we can directly assign it.
                # However, to be absolutely sure we don't lose top-card data if the parser
                # somehow returns "NA" for a field that top-card had, we can refine the merge:
                # Only update a field in self.current_job_data if the parser found something
                # *different from "NA"* for that field from the description text.
                # If the parser returns "NA" for a field, it means it didn't find it in the description,
                # so we should keep what was in self.current_job_data (from top-card).

                for key, value_from_parser in parsed_data_from_description.items():
                    if key in self.current_job_data:
                        # If parser found a specific value (not "NA"), update.
                        # Also, if the parser's value is an empty list (for skills) and current is NA, update.
                        # Or if the parser's value is 0 (for experience) and current is NA, update.
                        if value_from_parser != "NA":
                            self.current_job_data[key] = value_from_parser
                        # If parser has "NA" but current_job_data (top-card) had something, keep top-card.
                        # This is implicitly handled by not updating if value_from_parser is "NA" and current_job_data[key] was already set.
                    else:
                        # If the key is new (e.g. from description only, like 'mention_keywords'), add it.
                        self.current_job_data[key] = value_from_parser
                
                logger.info(f"Merged job data after description parse: {str(self.current_job_data)[:200]}...")
            else:
                logger.warning("Could not find job description text in _parse_job_description wrapper. current_job_data will rely solely on pre-filled (e.g., top-card) info.")
        
        except Exception as e:
            logger.error(f"Error in _parse_job_description wrapper: {e}", exc_info=True)
            # self.current_job_data (with its top-card info) should persist.

    def _close_easy_apply_modal(self):
        logger.info("Attempting to close Easy Apply modal...")
        closed_primary_modal_attempt = False
        try:
            close_button_selectors = [
                (By.CSS_SELECTOR, "button[data-test-modal-close-btn]"),
                (By.XPATH, "//button[contains(@aria-label,'Dismiss')]"),
                (By.XPATH, "//button[contains(@aria-label,'Close')]"),
                (By.CSS_SELECTOR, "li-icon[type='cancel-icon']"),
                (By.CSS_SELECTOR, "button.artdeco-modal__dismiss") 
            ]
            # Attempt to click a standard close button first
            for by_method, selector in close_button_selectors:
                try:
                    main_modal_close_button = self.driver.find_element(by_method, selector)
                    try:
                        save_dialog_check = main_modal_close_button.find_element(By.XPATH, "ancestor::div[@role='dialog' and .//h2[contains(., 'Save this application')]]")
                        if save_dialog_check:
                            logger.debug(f"Close button {selector} is part of 'Save application' dialog, skipping for now.")
                            continue 
                    except NoSuchElementException:
                        pass 

                    if main_modal_close_button.is_displayed() and main_modal_close_button.is_enabled():
                        logger.debug(f"Found main modal close button with selector: {selector}")
                        clicked_button = self._click_element_robustly(main_modal_close_button, "Main Modal Close Button")
                        if clicked_button:
                            logger.info("Clicked main modal close button (primary attempt).")
                            closed_primary_modal_attempt = True
                            break 
                except NoSuchElementException:
                    logger.debug(f"Main modal close button not found with selector: {selector}. Trying next.")
                    continue
                except Exception as e_click_close: 
                    logger.warning(f"Error interacting with main modal close button {selector}: {e_click_close}. Trying next.")
                    continue
            
            if not closed_primary_modal_attempt:
                logger.warning("Could not find or click a standard close/dismiss button on main modal. Attempting ESC key.")
                try:
                    easy_apply_modal_element = self.driver.find_element(By.CSS_SELECTOR, "div.jobs-easy-apply-modal[role='dialog']")
                    easy_apply_modal_element.send_keys(Keys.ESCAPE)
                    logger.info("Sent ESC key to Easy Apply modal to close it.")
                    closed_primary_modal_attempt = True 
                except Exception as e_esc:
                    logger.warning(f"Failed to send ESC key to modal or modal not found: {e_esc}")
                    active_element = self.driver.switch_to.active_element
                    if active_element:
                        active_element.send_keys(Keys.ESCAPE)
                        logger.info("Sent ESC key to active element as a fallback.")
                        closed_primary_modal_attempt = True
                    else:
                        logger.warning("No active element to send ESC key to.")

            self._dismiss_save_application_dialog() 

            try:
                WebDriverWait(self.driver, 5).until_not( 
                    EC.presence_of_element_located((By.CSS_SELECTOR, "div.jobs-easy-apply-modal[role='dialog']")) 
                )
                logger.info("Easy Apply modal (main) confirmed closed after all attempts.")
                return True
            except TimeoutException:
                logger.error("Failed to close Easy Apply modal (main) even after dismiss attempts and save dialog handling.")
                return False

        except Exception as e:
            logger.error(f"Outer exception in _close_easy_apply_modal: {e}", exc_info=True)
            return False

    def _dismiss_save_application_dialog(self, timeout=3) -> bool:
        try:
            dialog_wait = WebDriverWait(self.driver, timeout) 
            dialog = dialog_wait.until(
                EC.presence_of_element_located(
                    (By.XPATH,
                     "//div[@role='dialog' and .//h2[contains(., 'Save this application')]]")
                )
            )
            logger.info("Found 'Save this application?' confirmation dialog.")
            discard_btn = dialog.find_element( 
                By.XPATH, ".//button[normalize-space()='Discard' or normalize-space()='Cancel']"
            )
            self._click_element_robustly(discard_btn, "Save Application Dialog Discard Button")
            logger.info("Clicked 'Discard' on Save-application confirmation dialog.")
            dialog_wait.until(EC.staleness_of(dialog))
            logger.info("'Save this application?' dialog confirmed closed/stale.")
            return True
        except TimeoutException:
            logger.debug("'Save this application?' dialog did not appear within timeout.")
            return True 
        except Exception as e:
            logger.warning(f"Could not close 'Save this application?' dialog: {e}", exc_info=True)
            return False

    def _get_current_progress_value(self) -> "float | None":
        try:
            progress_element = self.driver.find_element(By.CSS_SELECTOR, "progress.artdeco-completeness-meter-linear__progress-element")
            return float(progress_element.get_attribute("aria-valuenow") or 0)
        except Exception:
            return None # Return None if progress bar not found or value not readable

    def _get_current_anchor_text(self) -> "str | None":
        try:
            by, generic_loc_str = STEP_ANCHORS[0]
            # Use a short wait as the anchor should ideally be present quickly if the page has loaded
            current_anchor_element = self.short_wait.until(EC.presence_of_element_located((by, generic_loc_str)))
            current_anchor_text_raw = self.driver.execute_script("return arguments[0].textContent;", current_anchor_element)
            
            if self.form_handler and hasattr(self.form_handler, '_norm'):
                return self.form_handler._norm(current_anchor_text_raw if current_anchor_text_raw else "")
            else:
                return " ".join(str(current_anchor_text_raw).split()).lower() if current_anchor_text_raw else ""
        except Exception:
            return None

    def _wait_for_step_transition(
        self,
        nav_button_elem: "WebElement | None", # The button that was clicked to trigger transition
        timeout: int = 120 # Overall timeout for confirming a transition
    ) -> bool:
        logger.info("Waiting for step transition...")
        start_time = time.perf_counter()

        # Initial state
        initial_anchor_text = self._last_anchor_text
        initial_progress_value = self._last_progress_value
        logger.debug(f"Transition check starting. Last anchor: '{initial_anchor_text}', Last progress: {initial_progress_value}%")

        # Primary loop to check for transition signals
        while time.perf_counter() - start_time < timeout:
            # 1. Check for button staleness (quickest check if button was provided)
            if nav_button_elem is not None:
                try:
                    if not nav_button_elem.is_displayed(): # Or other checks for staleness
                        logger.info("Nav button no longer displayed/stale. Transition confirmed by staleness.")
                        # Update current state before returning
                        self._last_anchor_text = self._get_current_anchor_text() or initial_anchor_text # Keep old if new not found
                        self._last_progress_value = self._get_current_progress_value() or initial_progress_value
                        logger.info(f"Post-staleness update. Anchor: '{self._last_anchor_text}', Progress: {self._last_progress_value}%")
                        return True
                except StaleElementReferenceException:
                    logger.info("Nav button became stale. Transition confirmed by StaleElementReferenceException.")
                    self._last_anchor_text = self._get_current_anchor_text() or initial_anchor_text
                    self._last_progress_value = self._get_current_progress_value() or initial_progress_value
                    logger.info(f"Post-staleness update. Anchor: '{self._last_anchor_text}', Progress: {self._last_progress_value}%")
                    return True
                except Exception as e_stale_check:
                    logger.debug(f"Minor error during staleness check: {e_stale_check}")


            # 2. Check for progress bar increase
            current_progress_value = self._get_current_progress_value()
            if current_progress_value is not None and initial_progress_value is not None:
                if current_progress_value > initial_progress_value:
                    logger.info(f"Progress bar value increased from {initial_progress_value}% to {current_progress_value}%. Transition confirmed.")
                    self._last_progress_value = current_progress_value
                    self._last_anchor_text = self._get_current_anchor_text() or initial_anchor_text # Update anchor as well
                    return True
            elif current_progress_value is not None and initial_progress_value is None: # First step after modal open
                 logger.debug(f"Progress value is {current_progress_value}%, but last was None (first step).")
                 # On the very first step, if _last_progress_value was None, any valid current_progress_value could be the new baseline
                 # But we need another signal (like anchor change) to confirm this first transition.
                 # However, if the button went stale, that's already a strong signal.

            # 3. Check for anchor text change
            current_anchor_text = self._get_current_anchor_text()
            if current_anchor_text is not None and current_anchor_text != initial_anchor_text:
                # Ensure text is not empty, unless it's the very first anchor being set from None
                if current_anchor_text or (initial_anchor_text is None and current_anchor_text == ""):
                    logger.info(f"Step anchor text changed to: '{current_anchor_text}' (was: '{initial_anchor_text}'). Transition confirmed.")
                    self._last_anchor_text = current_anchor_text
                    if current_progress_value is not None: # Update progress if anchor changed
                        self._last_progress_value = current_progress_value
                    return True
            
            # If no immediate confirmation, pause briefly before retrying checks
            time.sleep(0.5) # Polling interval

        # If loop finishes without returning True, timeout occurred
        logger.warning(f"No conditions for step transition met within {timeout}s (staleness, progress change, or new anchor text).")
        try:
            timestamp = time.strftime("%Y%m%d-%H%M%S")
            current_run_results_dir = self.results_dir or "."
            if not os.path.isdir(current_run_results_dir):
                base_path_for_debug = os.path.dirname(current_run_results_dir) if os.path.sep in current_run_results_dir else "."
                current_run_results_dir = os.path.join(base_path_for_debug, "debug_pages_transition_fail")
                os.makedirs(current_run_results_dir, exist_ok=True)
                logger.info(f"Debug HTML for transition fail will be in: {current_run_results_dir}")
            
            debug_html_path = os.path.join(current_run_results_dir, f"debug_step_transition_fail_{timestamp}.html")
            with open(debug_html_path, 'w', encoding='utf-8') as f:
                f.write(self.driver.page_source)
            logger.info(f"Saved page source for step transition failure to {debug_html_path}")
        except Exception as e_save:
            logger.error(f"Error saving debug page source on step transition failure: {e_save}")
        return False

    def apply_to_job(self, url):
        if not self.driver: print(f"Driver not initialized. Cannot apply to {url}."); return False
        logger.info(f"Attempting to apply to: {url}"); self.driver.get(url); time.sleep(random.uniform(2.5, 4.5))
        self._parse_job_description() 
        self._scroll_job_panel()

        try: 
            applied_text_xpath = "//*[contains(text(), 'Application submitted') or contains(., 'Applied')]"
            applied_elements = WebDriverWait(self.driver, 3).until(lambda d: d.find_elements(By.XPATH, applied_text_xpath), message="Timeout checking for 'Applied' status")
            if applied_elements and any(el.is_displayed() for el in applied_elements):
                if self.skip_if_applied_override:
                    logger.info(f"Job {url} indicates 'Application submitted' or 'Applied'. Skipping application as per skip_if_applied_override: True.")
                    return False 
                else:
                    logger.info(f"Job {url} indicates 'Application submitted' or 'Applied', but proceeding with application due to skip_if_applied_override: False.")
        except TimeoutException: 
            logger.debug(f"'Application submitted' or 'Applied' text not found for {url} (apply_to_job). Proceeding.")
        except Exception as e_applied_check: 
            logger.warning(f"Could not check for 'Application submitted' status in apply_to_job: {e_applied_check}. Proceeding.")
        
        try:
            timestamp = time.strftime("%Y%m%d-%H%M%S")
            sanitized_url_part = re.sub(r'[^a-zA-Z0-9_-]', '_', url.split('?')[0][-50:])
            ss_path = os.path.join(self.results_dir, f"pre_easy_apply_ss_{sanitized_url_part}_{timestamp}.png")
            self.driver.save_screenshot(ss_path)
            logger.info(f"Saved pre-EasyApply screenshot to {ss_path}")
        except Exception as e_ss:
            logger.error(f"Error saving pre-EasyApply screenshot: {e_ss}")
        
        _easy_apply_button_found_and_clicked = False
        easy_apply_selectors = [
            (By.CSS_SELECTOR, "button.jobs-apply-button--top-card"), 
            (By.CSS_SELECTOR, "div.jobs-unified-top-card__primary-actions button.jobs-apply-button"),
            (By.CSS_SELECTOR, "button#jobs-apply-button-id"), (By.ID, "jobs-apply-button-id"),
            (By.XPATH, "//button[contains(@aria-label, 'Easy Apply') or contains(@aria-label, 'Apply now')]"),
            (By.XPATH, "//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'easy apply')]"),
            (By.XPATH, "//button[.//span[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'easy apply')]]")
        ]
        clicked_easy_apply_button = None
        for by_method, selector_value in easy_apply_selectors:
            try:
                button = WebDriverWait(self.driver, 7).until(EC.presence_of_element_located((by_method, selector_value)))
                clicked_easy_apply_button = self._click_element_robustly(button, f"Easy Apply button (selector: {by_method} -> {selector_value})")
                if clicked_easy_apply_button:
                    _easy_apply_button_found_and_clicked = True; break 
            except: continue
        
        if not _easy_apply_button_found_and_clicked:
            logger.error(f"Could not click Easy Apply button for {url}. Cannot proceed.")
            return False

        # Initialize progress value and anchor text when modal first opens
        try:
            # Wait for modal to be generally present first
            WebDriverWait(self.driver, 5).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "div.jobs-easy-apply-modal__content"))
            )
            
            current_progress = self._get_current_progress_value()
            if current_progress is not None:
                self._last_progress_value = current_progress
                logger.info(f"Initial progress bar value set to: {self._last_progress_value}% after modal open.")
            else:
                logger.warning("Could not get initial progress bar value after modal open. _last_progress_value remains None.")
                self._last_progress_value = 0.0 # Default to 0 if not found, to allow first step progress increase

            current_anchor = self._get_current_anchor_text()
            if current_anchor is not None:
                self._last_anchor_text = current_anchor
                logger.info(f"Initial anchor text set to: '{self._last_anchor_text}' after modal open.")
            else:
                logger.warning("Could not get initial anchor text after modal open. _last_anchor_text remains None.")
                # self._last_anchor_text = None # It's already None from __init__

        except Exception as e_init_modal_state:
            logger.warning(f"Could not get initial progress or anchor text: {e_init_modal_state}. Proceeding with None/0.")
            self._last_progress_value = 0.0 # Default to 0 to allow first step progress increase
            self._last_anchor_text = None


        if not self._wait_for_step_transition(clicked_easy_apply_button): 
            logger.error(f"Easy Apply modal did not open or first step anchor not found for {url}.")
            self._close_easy_apply_modal() 
            return False

        current_step = 1; max_steps = 15; TEST_MODE_NO_SUBMIT = True 
        while current_step <= max_steps:
            logger.info(f"Processing application step {current_step} for {url}")
            modal_content_area = None
            try:
                modal_content_area = self.driver.find_element(By.CSS_SELECTOR, "div.jobs-easy-apply-modal__content")
            except NoSuchElementException:
                logger.warning("Could not find modal content area for validation check in apply_to_job.")

            if self.form_handler:
                self.form_handler._handle_form_fields(current_step, url, max_steps) 
                time.sleep(random.uniform(0.3, 0.7)) # Give a moment for UI to settle after filling

                # Check and handle validation errors before attempting to navigate
                if self.form_handler._check_and_handle_validation_errors(current_step_root_element=modal_content_area):
                    logger.info("Validation errors were handled in apply_to_job. Retrying navigation for current step.")
                    time.sleep(random.uniform(0.5, 1.0)) # Wait a bit after error handling
                    # Do not increment current_step, stay on the same step to re-attempt navigation
                    # The _wait_for_step_transition will be called again with the same _last_anchor_text and _last_progress_value
                    # so it should detect if the page *actually* changed or if it's just re-evaluating the same error page.
                    # We need to ensure that if _check_and_handle_validation_errors *fixed* something and the page reloads
                    # to the *same step* but without errors, our transition logic can handle it.
                    # The current transition logic relies on staleness, progress change, or anchor text change.
                    # If validation handling re-renders the same step without these changes, it might still fail.
                    # This needs careful thought. For now, let's assume validation handling might lead to a detectable transition.
                    # One way is to re-fetch anchor and progress *after* validation handling if it returns True.
                    
                    # Re-fetch current state after validation handling to update baselines if the page re-rendered
                    self._last_anchor_text = self._get_current_anchor_text() or self._last_anchor_text
                    self._last_progress_value = self._get_current_progress_value() or self._last_progress_value
                    logger.debug(f"Re-baselined after validation. Anchor: '{self._last_anchor_text}', Progress: {self._last_progress_value}%")
                    continue 
            else:
                logger.error("FormHandler not initialized. Cannot handle form fields.")
                self._close_easy_apply_modal()
                return False
            
            continue_selectors = [
                (By.CSS_SELECTOR, "button[aria-label='Continue to next step']"),
                (By.CSS_SELECTOR, "button[data-control-name='continue_unify']"),
                (By.XPATH, "//button[contains(translate(., 'NEXTCONTIUE', 'nextcontiue'), 'next') and not(contains(translate(., 'REVIEW', 'review'), 'review')) and not(contains(translate(., 'SUBMIT', 'submit'), 'submit'))]"),
                (By.XPATH, "//button[contains(translate(., 'NEXTCONTIUE', 'nextcontiue'), 'continue') and not(contains(translate(., 'REVIEW', 'review'), 'review')) and not(contains(translate(., 'SUBMIT', 'submit'), 'submit'))]")
            ]
            review_selectors = [
                (By.CSS_SELECTOR, "button[aria-label='Review your application']"),
                (By.XPATH, "//button[contains(translate(., 'REVIEWAPPLICATION', 'reviewapplication'), 'review application')]")
            ]
            submit_application_selectors = [
                (By.CSS_SELECTOR, "button[aria-label='Submit application']"),
                (By.CSS_SELECTOR, "button[data-control-name='submit_unify']"),
                (By.XPATH, "//button[contains(translate(., 'SUBMIT', 'submit'), 'submit application')]") 
            ]
            done_selectors = [ 
                (By.CSS_SELECTOR, "button[aria-label='Done']"),
                (By.XPATH, "//button[span[text()='Done']]"),
                (By.XPATH, "//button[text()='Done']")
            ]
            navigated_or_submitted = False
            clicked_nav_button = None 

            for by, sel in submit_application_selectors:
                try:
                    submit_button = self.short_wait.until(EC.element_to_be_clickable((by, sel)))
                    if submit_button.is_displayed() and submit_button.is_enabled():
                        logger.info(f"Found 'Submit application' button: {sel}")
                        if TEST_MODE_NO_SUBMIT:
                            logger.warning(f"[TEST MODE] Would click 'Submit application'. Simulating success.")
                        else:
                            self._click_element_robustly(submit_button, "Submit application button")
                            logger.info("Clicked 'Submit application'.")
                        time.sleep(random.uniform(1.5, 3)) 
                        done_clicked = False
                        for done_by, done_sel in done_selectors:
                            try:
                                done_button = self.short_wait.until(EC.element_to_be_clickable((done_by, done_sel)))
                                if done_button.is_displayed() and done_button.is_enabled():
                                    if TEST_MODE_NO_SUBMIT: logger.warning(f"[TEST MODE] Would click 'Done'.")
                                    else: self._click_element_robustly(done_button, "Done button"); logger.info("Clicked 'Done'.")
                                    done_clicked = True; return True 
                            except: continue
                        if not done_clicked: logger.warning("Clicked Submit, but 'Done' not found."); return True
                        return True 
                except: continue
            
            for by, sel in review_selectors:
                try:
                    review_button_el = self.short_wait.until(EC.element_to_be_clickable((by, sel)))
                    if review_button_el.is_displayed() and review_button_el.is_enabled():
                        logger.info(f"Found 'Review' button: {sel}. Clicking...")
                        clicked_nav_button = self._click_element_robustly(review_button_el, "Review button")
                        if clicked_nav_button: navigated_or_submitted = True; break
                except: continue
            
            if navigated_or_submitted: # This block handles Review button clicks
                transition_succeeded = self._wait_for_step_transition(clicked_nav_button)
                if not transition_succeeded:
                    current_modal_content_area = None
                    try:
                        current_modal_content_area = self.driver.find_element(By.CSS_SELECTOR, "div.jobs-easy-apply-modal__content")
                    except NoSuchElementException:
                        logger.warning("Could not find modal content area for validation check after Review click.")

                    if self.form_handler and self.form_handler._check_and_handle_validation_errors(current_step_root_element=current_modal_content_area):
                        logger.info("Validation errors handled after Review click, retrying current step's navigation logic.")
                        self._last_anchor_text = self._get_current_anchor_text() or self._last_anchor_text
                        self._last_progress_value = self._get_current_progress_value() or self._last_progress_value
                        continue 
                    else:
                        logger.error(f"Step transition failed after Review click for {url} and no validation errors handled. Aborting."); self._close_easy_apply_modal(); return False
                current_step += 1; continue


            clicked_nav_button = None # Reset for Continue button search
            for by, sel in continue_selectors:
                try:
                    continue_button_el = self.short_wait.until(EC.element_to_be_clickable((by, sel)))
                    if continue_button_el.is_displayed() and continue_button_el.is_enabled():
                        logger.info(f"Found 'Continue'/'Next' button: {sel}. Clicking...")
                        clicked_nav_button = self._click_element_robustly(continue_button_el, "Continue/Next button")
                        if clicked_nav_button: navigated_or_submitted = True; break 
                except: continue
            
            if navigated_or_submitted: # This block handles Continue/Next button clicks
                transition_succeeded = self._wait_for_step_transition(clicked_nav_button)
                if not transition_succeeded:
                    current_modal_content_area_cont = None
                    try:
                        current_modal_content_area_cont = self.driver.find_element(By.CSS_SELECTOR, "div.jobs-easy-apply-modal__content")
                    except NoSuchElementException:
                        logger.warning("Could not find modal content area for validation check after Continue/Next click.")
                        
                    if self.form_handler and self.form_handler._check_and_handle_validation_errors(current_step_root_element=current_modal_content_area_cont):
                        logger.info("Validation errors handled after Continue/Next click, retrying current step's navigation logic.")
                        self._last_anchor_text = self._get_current_anchor_text() or self._last_anchor_text
                        self._last_progress_value = self._get_current_progress_value() or self._last_progress_value
                        continue
                    else:
                        logger.error(f"Step transition failed after Continue/Next click for {url} and no validation errors handled. Aborting."); self._close_easy_apply_modal(); return False
                current_step += 1; continue
            
            logger.info(f"No actionable navigation (Continue, Review, Submit) button found at step {current_step}. Ending application attempt for {url}.")
            # Dump DOM if no nav buttons found
            self._dump_dom_for_debug(failed_selector_tuple=(By.CSS_SELECTOR, "button[aria-label='Generic Nav Button Not Found']"),
                                     context_selector_str="div.jobs-easy-apply-modal__content", # Try to get modal content
                                     failure_description=f"no_nav_buttons_step_{current_step}")
            self._close_easy_apply_modal(); return False 

        logger.warning(f"Reached max steps ({max_steps}) for job {url}. Application likely incomplete.")
        self._dump_dom_for_debug(failed_selector_tuple=(By.CSS_SELECTOR, "button[aria-label='Max Steps Reached']"),
                                 context_selector_str="div.jobs-easy-apply-modal__content",
                                 failure_description=f"max_steps_reached_{current_step}")
        self._close_easy_apply_modal(); return False

    def collect_application_questions(self, job_url):
        if not self.driver: logger.error(f"Driver not initialized. Cannot collect questions for {job_url}."); return []
        logger.info(f"Attempting to collect questions from: {job_url}"); self.driver.get(job_url); time.sleep(3)
        
        self.current_job_url_for_debug = job_url # Store for debug filenames
        
        # Initialize current_job_data for this job
        self.current_job_data = {
            "job_title": self._get_job_title_from_top_card(),
            "company_name": self._get_company_name_from_top_card(),
            "location": self._get_location_from_top_card(),
            "employment_type": self._get_employment_type_from_top_card()
        }
        logger.info(f"Initial top-card scrape: Title='{self.current_job_data['job_title']}', Company='{self.current_job_data['company_name']}', Location='{self.current_job_data['location']}', EmpType='{self.current_job_data['employment_type']}'")

        # Now parse the description, which will fill in or augment self.current_job_data
        self._parse_job_description() 
        
        # Ensure company_name is set, falling back if needed
        if not self.current_job_data.get("company_name"):
            self.current_job_data["company_name"] = self._get_company_name_from_top_card() or "Unknown Company"
        
        company_name = self.current_job_data.get("company_name", "Unknown Company")
        collected_questions_data = []; collected_question_labels_for_this_job = set()
        
        try:
            applied_text_xpath = "//*[contains(text(), 'Application submitted') or contains(., 'Applied')]"
            applied_elements = WebDriverWait(self.driver, 3).until(lambda d: d.find_elements(By.XPATH, applied_text_xpath), message="Timeout checking for 'Applied' status")
            if applied_elements and any(el.is_displayed() for el in applied_elements):
                if self.skip_if_applied_override: 
                    logger.info(f"Job {job_url} indicates 'Application submitted' or 'Applied'. Skipping as per skip_if_applied_override: True.")
                    return []
                else:
                    logger.info(f"Job {job_url} indicates 'Application submitted' or 'Applied', but proceeding due to skip_if_applied_override: False.")
        except TimeoutException: 
            logger.debug(f"'Application submitted' or 'Applied' text not found for {job_url}. Proceeding.")
        except Exception as e_applied_check: 
            logger.warning(f"Could not check for 'Application submitted' status: {e_applied_check}. Proceeding.")

        self._scroll_job_panel()
        easy_apply_button_found = False
        clicked_easy_apply_button_element = None
        easy_apply_selectors = [(By.CSS_SELECTOR, "button.jobs-apply-button--top-card"), (By.CSS_SELECTOR, "div.jobs-unified-top-card__primary-actions button.jobs-apply-button"), (By.CSS_SELECTOR, "button#jobs-apply-button-id"), (By.ID, "jobs-apply-button-id"), (By.XPATH, "//button[contains(@aria-label, 'Easy Apply') or contains(@aria-label, 'Apply now')]"), (By.XPATH, "//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'easy apply')]"), (By.XPATH, "//button[.//span[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'easy apply')]]"), (By.CSS_SELECTOR, ".jobs-s-apply button"), (By.CSS_SELECTOR, "button.jobs-apply-button")]
        
        for by_method, selector_value in easy_apply_selectors:
            try:
                logger.debug(f"Trying Easy Apply: {by_method} -> {selector_value}"); 
                button = WebDriverWait(self.driver, 7).until(EC.presence_of_element_located((by_method, selector_value))) 
                clicked_easy_apply_button_element = self._click_element_robustly(button, "Easy Apply button (collection)")
                if clicked_easy_apply_button_element:
                    easy_apply_button_found = True; logger.info(f"Clicked Easy Apply with: {by_method} -> {selector_value} using robust click."); break
            except: continue
        
        if not easy_apply_button_found: logger.error(f"Could not click Easy Apply for {job_url}."); return collected_questions_data
        
        # Initialize progress and anchor text for question collection
        try:
            WebDriverWait(self.driver, 5).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "div.jobs-easy-apply-modal__content"))
            )
            current_progress = self._get_current_progress_value()
            if current_progress is not None:
                self._last_progress_value = current_progress
                logger.info(f"Initial progress (collection): {self._last_progress_value}%")
            else: self._last_progress_value = 0.0
            
            current_anchor = self._get_current_anchor_text()
            if current_anchor is not None:
                self._last_anchor_text = current_anchor
                logger.info(f"Initial anchor (collection): '{self._last_anchor_text}'")
            else: self._last_anchor_text = None
        except Exception as e_init_modal_state_collect:
            logger.warning(f"Could not get initial progress/anchor (collection): {e_init_modal_state_collect}")
            self._last_progress_value = 0.0
            self._last_anchor_text = None


        if not self._wait_for_step_transition(clicked_easy_apply_button_element):
             logger.error(f"Easy Apply modal did not open or first step anchor not found for {job_url} (question collection).")
             self._close_easy_apply_modal(); return collected_questions_data

        current_step = 1; max_steps = 15; consecutive_no_new_questions = 0
        while current_step <= max_steps:
            logger.info(f"Collecting questions: step {current_step}");
            modal_content_area_collect = None
            try:
                modal_content_area_collect = self.driver.find_element(By.CSS_SELECTOR, "div.jobs-easy-apply-modal__content")
            except NoSuchElementException:
                logger.warning("Could not find modal content area for validation check in collect_application_questions.")

            if not self.form_handler:
                logger.error("FormHandler not initialized in collect_application_questions. Aborting."); break
            
            step_questions = self.form_handler._extract_fields_for_question_collection()
            
            if self.form_handler._check_and_handle_validation_errors(current_step_root_element=modal_content_area_collect):
                logger.info("Validation errors were handled in collect_application_questions. Retrying navigation for current step.")
                time.sleep(random.uniform(0.5, 1.0)) 
                self._last_anchor_text = self._get_current_anchor_text() or self._last_anchor_text
                self._last_progress_value = self._get_current_progress_value() or self._last_progress_value
                continue 

            new_questions_found_this_step = False
            for q_info in step_questions:
                normalized_label = re.sub(r'\s+', ' ', q_info["label"].strip().lower())
                if normalized_label not in collected_question_labels_for_this_job:
                    collected_questions_data.append({"job_url": job_url, "company": company_name, "question_label": q_info["label"], "input_type": q_info["type"], "options": q_info.get("options"), "is_required": q_info.get("is_required", False)}); collected_question_labels_for_this_job.add(normalized_label); new_questions_found_this_step = True
            
            if not new_questions_found_this_step and step_questions: logger.info(f"Step {current_step}: All questions seem duplicates."); consecutive_no_new_questions +=1
            else: consecutive_no_new_questions = 0
            if consecutive_no_new_questions >= 3: logger.info("No new questions for 3 consecutive steps. Ending collection for this job."); break 

            navigated = False
            clicked_nav_button_element = None
            primary_next_selectors = [(By.CSS_SELECTOR, "button[aria-label='Continue to next step']"), (By.XPATH, "//button[contains(text(),'Continue to next step')]")]
            review_button_selectors = [(By.CSS_SELECTOR, "button[aria-label='Review your application']"), (By.XPATH, "//button[contains(text(),'Review your application')]")]
            submit_button_selectors = [(By.CSS_SELECTOR, "button[aria-label='Submit application']")]

            for by_m, sel in primary_next_selectors:
                try:
                    btn_el = self.short_wait.until(EC.element_to_be_clickable((by_m, sel)))
                    if btn_el.is_displayed() and btn_el.is_enabled():
                        logger.info(f"Found primary nav: {sel}. Clicking.")
                        clicked_nav_button_element = self._click_element_robustly(btn_el, "Next/Continue")
                        if clicked_nav_button_element: navigated = True; break
                except: continue
            
            if navigated:
                transition_succeeded = self._wait_for_step_transition(clicked_nav_button_element)
                if not transition_succeeded:
                    if self.form_handler and self.form_handler._check_and_handle_validation_errors():
                        logger.info("Validation errors handled after Next/Continue, retrying current step.")
                        self._last_anchor_text = self._get_current_anchor_text() or self._last_anchor_text
                        self._last_progress_value = self._get_current_progress_value() or self._last_progress_value
                        continue 
                    else:
                        logger.error(f"Step transition failed after Next/Continue for {job_url} and no validation errors handled. Ending collection."); break
                current_step += 1; continue
            
            should_try_review = new_questions_found_this_step or not step_questions or current_step < 3 or consecutive_no_new_questions < 2
            if should_try_review:
                clicked_nav_button_element = None 
                for by_m, sel in review_button_selectors:
                    try:
                        btn_el = self.short_wait.until(EC.element_to_be_clickable((by_m, sel)))
                        if btn_el.is_displayed() and btn_el.is_enabled():
                            if any(len(self.driver.find_elements(s_b, s_v)) > 0 for s_b, s_v in submit_button_selectors):
                                logger.info(f"Review button ({sel}) found, but Submit also present. Ending."); break 
                            logger.info(f"Found Review button: {sel}. Clicking.")
                            clicked_nav_button_element = self._click_element_robustly(btn_el, "Review button")
                            if clicked_nav_button_element: navigated = True; break
                    except: continue
                if navigated: 
                    transition_succeeded = self._wait_for_step_transition(clicked_nav_button_element)
                    if not transition_succeeded:
                        if self.form_handler and self.form_handler._check_and_handle_validation_errors():
                            logger.info("Validation errors handled after Review click, retrying current step.")
                            self._last_anchor_text = self._get_current_anchor_text() or self._last_anchor_text
                            self._last_progress_value = self._get_current_progress_value() or self._last_progress_value
                            continue
                        else:
                            logger.error(f"Step transition failed after Review click for {job_url} and no validation errors handled. Ending collection."); break
                    current_step += 1; continue
                elif any(len(self.driver.find_elements(s_b, s_v)) > 0 for s_b, s_v in submit_button_selectors): 
                    break 
            else: 
                logger.info("No new questions and no primary Next. Avoiding Review.")

            logger.info(f"No further nav buttons at step {current_step}. Checking Submit."); 
            is_submit_final = any(len(self.driver.find_elements(s_b,s_v)) > 0 and self.driver.find_element(s_b,s_v).is_displayed() for s_b,s_v in submit_button_selectors)
            if is_submit_final: 
                logger.info("Submit button detected. Form traversed for question collection.")
            else: 
                logger.info("No Submit, no other nav. Assuming end of flow for question collection.")
                self._dump_dom_for_debug(failed_selector_tuple=(By.CSS_SELECTOR, "button[aria-label='Generic Nav Button Not Found Collect']"),
                                         context_selector_str="div.jobs-easy-apply-modal__content",
                                         failure_description=f"no_nav_buttons_collect_step_{current_step}")
            break 
        
        if current_step > max_steps: 
            logger.warning(f"Max steps ({max_steps}) reached for {job_url} during question collection.")
            self._dump_dom_for_debug(failed_selector_tuple=(By.CSS_SELECTOR, "button[aria-label='Max Steps Reached Collect']"),
                                     context_selector_str="div.jobs-easy-apply-modal__content",
                                     failure_description=f"max_steps_reached_collect_{current_step}")
        self._close_easy_apply_modal()
        return collected_questions_data

    def _get_company_name(self):
        try:
            selectors = [".jobs-unified-top-card__company-name a", ".jobs-unified-top-card__company-name", ".topcard__org-name-link", "a[data-tracking-control-name='public_jobs_topcard_org_name']"]
            for selector in selectors:
                try:
                    el = self.driver.find_element(By.CSS_SELECTOR, selector)
                    if el.is_displayed() and el.text.strip():
                        name = el.text.strip().lower()
                        return re.sub(r'\s+(inc\.?|llc|corp\.?|corporation|group|ltd\.?)$', '', name, flags=re.IGNORECASE)
                except: continue
        except Exception as e: logger.error(f"Error extracting company name: {e}")
        return None
    
    def _get_answer_for_question(self, question_text, is_dropdown=False):
        if not question_text: return None
        question_text_normalized = question_text.lower().strip()
        company_name = self.current_job_data.get("company_name", self._get_company_name() or "Unknown Company")

        if company_name and company_name in self.form_answers.get("company_specific", {}):
            company_answers = self.form_answers["company_specific"][company_name]
            for q_pattern, answer in company_answers.items():
                if q_pattern.lower() in question_text_normalized:
                    logger.info(f"Using company-specific answer for '{question_text_normalized}': {answer}")
                    return answer
        
        label_lower = question_text_normalized 
        if 'email' in label_lower: return self.email 
        if 'phone' in label_lower and not is_dropdown : return self.resume_data.get("phone") 
        if any(kw in label_lower for kw in ['first name', 'firstname']): return self.resume_data.get("first_name")
        if any(kw in label_lower for kw in ['last name', 'lastname', 'surname']): return self.resume_data.get("last_name")

        numeric_defaults = self.form_answers.get("numeric_defaults", {})
        years_experience_match = re.search(r'(how many |)years? (of work |of |)experience (with|in|do you have with) (\w+(\s\w+)*)', question_text_normalized)
        if years_experience_match:
            skill = years_experience_match.group(4).lower() 
            skill_years = self._get_skill_years(skill)
            if skill_years is not None: return str(skill_years)

        if is_dropdown or ("how many years" not in question_text_normalized and "how much experience" not in question_text_normalized) :
            exp_skill_match = None
            patterns = [
                r'(?:experience\s+(?:with|in|using)|proficient\s+in|familiar\s+with|knowledge\s+of|worked\s+with|used)\s+([\w\s\+\-\#\./]+)\??$',
                r'(?:do\s+you\s+have|any|are\s+you)\s+(?:experience|proficiency|familiarity|knowledge)\s+(?:with|in|of)\s+([\w\s\+\-\#\./]+)\??$'
            ]
            for pat in patterns:
                match = re.search(pat, question_text_normalized, re.IGNORECASE)
                if match: exp_skill_match = match; break
            
            if exp_skill_match:
                skill_in_question = exp_skill_match.group(1).strip().lower()
                resume_skills_lower = [s.lower() for s in self.resume_data.get("skills", [])]
                experience_yes_keywords_lower = [k.lower() for k in self.form_answers.get("experience_yes_keywords", [])]
                has_skill_on_resume = False
                for resume_skill in resume_skills_lower:
                    if skill_in_question in resume_skill or resume_skill in skill_in_question:
                        has_skill_on_resume = True; break
                
                if has_skill_on_resume:
                    should_say_yes = False
                    for yes_keyword in experience_yes_keywords_lower:
                        if skill_in_question in yes_keyword or yes_keyword in skill_in_question:
                            should_say_yes = True; break
                    
                    if should_say_yes:
                        logger.info(f"Answering 'Yes' to experience question about '{skill_in_question}' based on resume and experience_yes_keywords.")
                        return "Yes" 
                    else:
                        logger.info(f"Skill '{skill_in_question}' is on resume but not in 'experience_yes_keywords'. Will fall through to general maps or default for this Yes/No question.")
                else: 
                    logger.info(f"Skill '{skill_in_question}' not found on resume. Answering 'No' for experience question.")
                    return "No" 

        answers_map = self.form_answers.get("dropdown_map", {}) if is_dropdown else self.form_answers.get("text_map", {})
        for q_pattern, answer in answers_map.items():
            if q_pattern.lower() in question_text_normalized:
                if isinstance(answer, str) and answer.startswith("LLM_CANDIDATE_"):
                    if self.use_llm and self.openai_client:
                        contextual_answer = self._generate_contextual_llm_answer(question_text)
                        return contextual_answer if contextual_answer and contextual_answer.strip().upper() != "N/A" else (self.form_answers.get("default_text", "N/A") if not is_dropdown else self.form_answers.get("default_dropdown", "Yes"))
                    else: return self.form_answers.get("default_text", "N/A") if not is_dropdown else self.form_answers.get("default_dropdown", "Yes")
                return answer
        
        if not is_dropdown and self.use_llm and self.openai_client: 
            pii_keywords_for_llm_skip = ["name", "email", "phone", "city", "state", "zip", "country", "address", "location", "resume", "cover letter", "portfolio", "linkedin", "github", "website"]
            if len(question_text_normalized.split()) > 3 and not any(kw in question_text_normalized for kw in pii_keywords_for_llm_skip): 
                llm_answer = self._generate_contextual_llm_answer(question_text)
                if llm_answer and llm_answer.strip().upper() != "N/A": return llm_answer
        
        return None if not is_dropdown else self.form_answers.get("default_dropdown", "Yes")

    def _get_skill_years(self, skill):
        skill = skill.lower()
        if self.resume_data and "skill_durations" in self.resume_data:
            skill_durations = self.resume_data["skill_durations"]
            if skill in skill_durations and skill_durations[skill].get("years") is not None: return skill_durations[skill]["years"]
            for k, data in skill_durations.items():
                if (skill in k or k in skill) and data.get("years") is not None: return data["years"]
        return self.form_answers.get("numeric_defaults", {}).get("years_skill", 2) 

    def _generate_llm_company_answer(self, company, domain, skills_text, technologies):
        if not self.use_llm or not self.openai_client:
            logger.info("LLM disabled or client not init for company interest.")
            template = self.form_answers.get("text_map", {}).get("why do you want to work at", "") or "Default company interest answer."
            return template.format(company=company, domain=domain, skills=skills_text, technologies=technologies)
        prompt = f"Generate a 150-word professional response to \"Why do you want to work at {company}?\"..."
        try:
            response = self.openai_client.chat.completions.create(model="gpt-3.5-turbo", messages=[{"role": "user", "content": prompt}], max_tokens=200)
            return response.choices[0].message.content.strip()
        except openai.APIError as e: logger.error(f"OpenAI APIError for company answer: {e}")
        except Exception as e: logger.error(f"Unexpected error in LLM company answer: {e}")
        return "Default company interest answer on error."

    def _generate_contextual_llm_answer(self, question_text):
        if not self.use_llm or not self.openai_client:
            logger.info("LLM disabled or client not init for contextual answer.")
            return "N/A"
        logger.info(f"Attempting contextual LLM for: {question_text}")
        resume_context_str = "Key Skills: Python, Machine Learning. Experience: 5 years as ML Engineer." 
        job_context_str = f"Job: {self.current_job_data.get('job_title', 'role')} at {self.current_job_data.get('company_name', 'company')}." 
        prompt = f"Resume: {resume_context_str}\nJob: {job_context_str}\nQuestion: {question_text}\nAnswer concisely:"
        try:
            response = self.openai_client.chat.completions.create(model="gpt-3.5-turbo", messages=[{"role": "user", "content": prompt}], max_tokens=150)
            answer = response.choices[0].message.content.strip()
            logger.info(f"Contextual LLM response for '{question_text}': {answer}")
            return answer if answer.lower() not in ["n/a", "not applicable."] else "N/A"
        except openai.APIError as e: logger.error(f"OpenAI APIError for contextual answer: {e}")
        except Exception as e: logger.error(f"Unexpected error in contextual LLM: {e}")
        return "N/A"

    def _generate_llm_generic_answer(self, question_text, company_name=None):
        logger.info(f"Delegating generic LLM for '{question_text}' to contextual.")
        return self._generate_contextual_llm_answer(question_text)

    def _dump_dom_for_debug(self, failed_selector_tuple: tuple, context_selector_str: str = "body", failure_description: str = "selector_fail"):
        """
        Dumps a portion of the current DOM to a file for debugging selector issues.

        Args:
            failed_selector_tuple (tuple): The (By, value) tuple of the selector that failed.
            context_selector_str (str, optional): A CSS selector for a parent/context element whose outerHTML should be dumped.
                                                 Defaults to "body".
            failure_description (str, optional): A short description for the filename.
        """
        if not self.driver:
            logger.error("DOM Dump: Driver not available.")
            return

        try:
            timestamp = time.strftime("%Y%m%d-%H%M%S")
            by_method, selector_value = failed_selector_tuple
            selector_value_str = str(selector_value) # Ensure it's a string for filename operations
            selector_str_for_filename = re.sub(r'[^a-zA-Z0-9_-]', '_', selector_value_str)[:50]
            
            job_url_part_for_filename = ""
            if hasattr(self, 'current_job_url_for_debug') and self.current_job_url_for_debug:
                sanitized_job_url = re.sub(r'[^a-zA-Z0-9_-]', '_', self.current_job_url_for_debug.split('?')[0][-40:])
                job_url_part_for_filename = f"{sanitized_job_url}_"

            current_run_results_dir = self.results_dir or "."
            debug_dom_dir = os.path.join(current_run_results_dir, "debug_dom_dumps")
            
            if not os.path.isdir(debug_dom_dir):
                try:
                    os.makedirs(debug_dom_dir, exist_ok=True)
                    logger.info(f"Created debug DOM dump directory: {debug_dom_dir}")
                except OSError as e_mkdir:
                    logger.error(f"Could not create DOM dump directory {debug_dom_dir}, using {current_run_results_dir}. Error: {e_mkdir}")
                    debug_dom_dir = current_run_results_dir if os.path.isdir(current_run_results_dir) else "."

            filename = f"{failure_description}_{job_url_part_for_filename}{selector_str_for_filename}_{timestamp}.html"
            filepath = os.path.join(debug_dom_dir, filename)

            dump_html = ""
            captured_context_info = "None" # To store what context was actually captured

            # Attempt 1: Provided context_selector_str
            try:
                context_element = self.driver.find_element(By.CSS_SELECTOR, context_selector_str)
                dump_html = context_element.get_attribute("outerHTML")
                logger.info(f"DOM Dump: Captured outerHTML of '{context_selector_str}'.")
                captured_context_info = context_selector_str
            except NoSuchElementException:
                logger.warning(f"DOM Dump: Provided context selector '{context_selector_str}' not found. Trying fallbacks.")
            except Exception as e_context_specific:
                logger.warning(f"DOM Dump: Error getting outerHTML for context selector '{context_selector_str}': {e_context_specific}. Trying fallbacks.")

            # Attempt 2: Easy Apply Modal (if initial context failed or was default body and modal might be active)
            if not dump_html:
                modal_selector = "div.jobs-easy-apply-modal[role='dialog']"
                try:
                    modal_element = self.driver.find_element(By.CSS_SELECTOR, modal_selector)
                    if modal_element.is_displayed():
                        dump_html = modal_element.get_attribute("outerHTML")
                        logger.info("DOM Dump: Captured outerHTML of Easy Apply modal as fallback context.")
                        captured_context_info = "EasyApplyModal"
                except NoSuchElementException:
                    logger.debug("DOM Dump: Easy Apply modal not found as fallback context.")
                except Exception as e_modal_fallback:
                    logger.warning(f"DOM Dump: Error getting outerHTML for Easy Apply modal fallback: {e_modal_fallback}")
            
            # Attempt 3: Body (if still no HTML)
            if not dump_html:
                logger.info("DOM Dump: Trying body as context.")
                try:
                    body_element = self.driver.find_element(By.TAG_NAME, "body")
                    dump_html = body_element.get_attribute("outerHTML")
                    logger.info("DOM Dump: Captured outerHTML of body.")
                    captured_context_info = "body"
                except Exception as e_body:
                    logger.error(f"DOM Dump: Could not get body HTML: {e_body}. Page source as last resort.")
                    # Fallback to full page source will happen below if dump_html is still empty
            
            # Final Fallback: Full page source if dump_html is still empty
            if not dump_html:
                logger.warning("DOM Dump: Captured HTML was empty through specific contexts, falling back to full page source.")
                dump_html = self.driver.page_source
                captured_context_info = "full_page_source"

            with open(filepath, "w", encoding="utf-8") as f:
                f.write(f"<!-- Debug DOM Dump for failed selector: {by_method} :: {selector_value_str} -->\n")
                f.write(f"<!-- Context captured: {captured_context_info} -->\n")
                f.write(f"<!-- Current URL: {self.driver.current_url} -->\n")
                f.write(dump_html)
            logger.info(f"DOM Dump: Saved debug DOM to {filepath}")

        except Exception as e:
            logger.error(f"DOM Dump: General error in _dump_dom_for_debug: {e}", exc_info=True)

    def collect_job_details(self, job_url: str) -> Dict[str, Any]:
        """
        Collects job details (parsed description and application link) for a given job URL.
        Returns a dictionary with all relevant job facts and the application link.
        """
        if not self.driver:
            logger.error(f"Driver not initialized. Cannot collect job details for {job_url}.")
            return {}
        logger.info(f"Collecting job details from: {job_url}")
        
        # Store current window handle
        original_window = self.driver.current_window_handle
        
        # Open job URL in a new tab
        self.driver.execute_script(f"window.open('{job_url}', '_blank');")
        
        # Switch to the new tab
        new_window = [window for window in self.driver.window_handles if window != original_window][0]
        self.driver.switch_to.window(new_window)
        
        time.sleep(3) # Wait for page to load in new tab
        
        self.current_job_url_for_debug = job_url # Store for debug filenames

        # Initialize current_job_data for this job
        self.current_job_data = {
            "job_title": self._get_job_title_from_top_card(),
            "company_name": self._get_company_name_from_top_card(),
            "location": self._get_location_from_top_card(),
            "employment_type": self._get_employment_type_from_top_card()
        }
        logger.info(f"Initial top-card scrape for {job_url}: Title='{self.current_job_data['job_title']}', Company='{self.current_job_data['company_name']}', Location='{self.current_job_data['location']}', EmpType='{self.current_job_data['employment_type']}'")
        
        # Now parse the description, which will fill in or augment self.current_job_data
        self._parse_job_description() # This will use self.current_job_data
        
        job_facts = dict(self.current_job_data) # Make a copy to return
        job_facts["job_url"] = job_url
        relative_html_path = "" # Initialize

        # --- Modified HTML dumping ---
        # The job page HTML is saved for debugging and comparison purposes.
        # Naming convention: job_page_html/job_<job_id>.html
        # The <job_id> is extracted from the job_url.
        # The method returns a relative path to this saved HTML file,
        # which is then typically stored in the output CSV.
        try:
            # 1. Extract Job ID
            job_id_match = re.search(r'/jobs/view/(\d+)/', job_url)
            if job_id_match:
                job_id = job_id_match.group(1)
            else:
                # Fallback if the standard job ID format isn't found in the URL
                job_id = "unknown_job_id_" + re.sub(r'[^a-zA-Z0-9_-]', '_', job_url.split('?')[0][-30:])
                logger.warning(f"Could not extract job ID from URL: {job_url}. Using fallback: {job_id}")

            # 2. Create job_page_html directory within the main results directory
            results_dir_path = self.results_dir or "." # self.results_dir is set by main.py
            job_page_html_dir = os.path.join(results_dir_path, "job_page_html")
            os.makedirs(job_page_html_dir, exist_ok=True)

            # 3. Construct new HTML filename and paths
            # The filename uses the extracted job_id.
            html_filename = f"job_{job_id}.html"
            # relative_html_path is what's returned and saved in the CSV.
            # It's relative to the main results_dir.
            relative_html_path = os.path.join("job_page_html", html_filename) 
            full_html_path = os.path.join(job_page_html_dir, html_filename) # Full path for saving the file

            with open(full_html_path, 'w', encoding='utf-8') as f:
                f.write(self.driver.page_source) # Save the full page source
            logger.info(f"Saved job page HTML for job ID {job_id} to {full_html_path}")

        except Exception as e_save_html:
            logger.error(f"Error saving job page HTML for {job_url} (ID: {job_id if 'job_id' in locals() else 'unknown'}): {e_save_html}")
            relative_html_path = "Error saving HTML" # Indicate error in the returned path if saving fails
        # --- End Modified HTML dumping ---

        # Try to find the application link
        app_link = ""
        try:
            # Look for buttons/links that might lead to application or are the application page itself
            # Prioritize Easy Apply button if present
            easy_apply_button_selectors = [
                (By.CSS_SELECTOR, "button.jobs-apply-button--top-card"), 
                (By.CSS_SELECTOR, "div.jobs-unified-top-card__primary-actions button.jobs-apply-button"),
                (By.XPATH, "//button[contains(@aria-label, 'Easy Apply') or contains(@aria-label, 'Apply now')]")
            ]
            found_easy_apply_href = None
            for by_method, selector_value in easy_apply_button_selectors:
                try:
                    button = self.driver.find_element(by_method, selector_value)
                    if button.is_displayed():
                        # If it's an anchor tag itself, get href
                        if button.tag_name == 'a':
                            found_easy_apply_href = button.get_attribute('href')
                            if found_easy_apply_href: break
                        # If it's a button that might trigger a modal or redirect, the current URL might be best
                        # For now, let's assume if an Easy Apply button is found, the job_url is the primary link
                        found_easy_apply_href = job_url # Default to job_url if button found
                        break 
                except NoSuchElementException:
                    continue
            
            if found_easy_apply_href:
                app_link = found_easy_apply_href
            else:
                # Fallback: if no specific Easy Apply button, check for general apply links or use current URL
                apply_links = self.driver.find_elements(By.XPATH, "//a[contains(@href, '/jobs/apply/') or contains(@href, '/jobs/view/')]")
                if apply_links:
                    app_link = apply_links[0].get_attribute("href")
                else:
                    app_link = self.driver.current_url # Current URL of the new tab
        except Exception as e:
            logger.warning(f"Could not extract application link: {e}")
            app_link = job_url # Fallback to the original job URL
            
        job_facts["application_link"] = app_link
        
        # Close the new tab and switch back to the original window
        self.driver.close()
        self.driver.switch_to.window(original_window)
        
        return job_facts, relative_html_path

    def close(self):
        if self.driver:
            self.driver.quit()
            print("WebDriver closed.")
        self.driver = None
        self.wait = None
        self.short_wait = None
