import asyncio
import yaml
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
import re # For cleaning job URLs

async def get_job_url_from_search(page, search_query, date_filter_text):
    """
    Performs a job search and extracts the first job URL.
    """
    print("Navigating to LinkedIn jobs page...")
    try:
        await page.goto("https://www.linkedin.com/jobs/", timeout=60000, wait_until="domcontentloaded")
        print("LinkedIn jobs page: DOM content loaded.")
        await page.screenshot(path="playwright_jobs_page_domloaded.png") # Crucial screenshot
        print("Screenshot taken: playwright_jobs_page_domloaded.png")

        print("Now waiting for network to become idle...")
        await page.wait_for_load_state('networkidle', timeout=60000) # Re-ensure network idle
        print("LinkedIn jobs page: Network is idle.")
        await page.screenshot(path="playwright_jobs_page_networkidle.png") # Screenshot after network idle
        print("Screenshot taken: playwright_jobs_page_networkidle.png")

    except PlaywrightTimeoutError as pte:
        current_url = page.url
        print(f"Timeout during jobs page navigation (goto/domcontentloaded or networkidle). Current URL: {current_url}")
        print(f"Error details: {pte}")
        try:
            await page.screenshot(path="playwright_jobs_page_nav_timeout.png")
            print("Screenshot: playwright_jobs_page_nav_timeout.png")
            content = await page.content(timeout=5000)
            with open("playwright_jobs_page_nav_timeout_content.html", "w", encoding="utf-8") as f:
                f.write(content)
            print("Page content at timeout saved.")
        except Exception as e_diag:
            print(f"Could not save diagnostic info during nav timeout: {e_diag}")
        return None
    except Exception as e: # Catch other potential navigation errors
        current_url = page.url
        print(f"An unexpected error occurred during jobs page navigation. Current URL: {current_url}")
        print(f"Error details: {e}")
        try:
            await page.screenshot(path="playwright_jobs_page_nav_error.png")
            print("Screenshot: playwright_jobs_page_nav_error.png")
        except Exception as e_ss_err:
            print(f"Could not take screenshot during nav error: {e_ss_err}")
        return None

    keyword_search_box_selectors = [
        "input.jobs-search-box__text-input[id*='jobs-search-box-keyword-id']",
        "input[aria-label*='Search by title'][aria-label*='skill'][aria-label*='company']",
        "input.jobs-search-box__text-input",
        "input[id^='jobs-search-box-keyword']",
        "input[placeholder*='Search jobs']", # This one timed out normally before
        "input.search-global-typeahead__input"
    ]
    location_search_box_selector = "input.jobs-search-box__text-input[id*='jobs-search-box-location-id']"

    active_keyword_search_selector = None
    keyword_search_box_element = None

    # Add a brief pause IF NEEDED, after networkidle, if elements are still slow to initialize
    # print("Brief pause for UI to settle after network idle...")
    # await page.wait_for_timeout(2000) # e.g., 2 seconds

    for i, selector_str in enumerate(keyword_search_box_selectors):
        try:
            print(f"Attempting to locate keyword search box with selector ({i+1}): {selector_str}")
            current_locator = page.locator(selector_str).first

            # Try waiting for 'attached' first, then 'visible', then 'enabled'
            print(f"  Waiting for selector ({i+1}) to be ATTACHED: {selector_str}")
            await current_locator.wait_for(state="attached", timeout=5000) # Shorter timeout for attached state

            print(f"  Waiting for selector ({i+1}) to be VISIBLE: {selector_str}")
            await current_locator.wait_for(state="visible", timeout=10000)
            
            print(f"  Waiting for selector ({i+1}) to be ENABLED: {selector_str}")
            await current_locator.wait_for(state="enabled", timeout=10000)
            
            print(f"Keyword search box found, attached, visible, and enabled with selector: {selector_str}")
            active_keyword_search_selector = selector_str
            keyword_search_box_element = current_locator
            break 
        except PlaywrightTimeoutError:
            print(f"Timeout: Keyword search box selector {selector_str} not attached/visible/enabled in time.")
        except Exception as e_sel:
            print(f"Error with selector {selector_str}: {e_sel}") # This will show the "state: expected..." error
            if "state: expected one of" in str(e_sel):
                print(f"   INFO: This selector ({selector_str}) resulted in the 'state: expected one of...' error. Check screenshots.")
                # Consider taking a screenshot specific to this error occurrence if it's intermittent
                # await page.screenshot(path=f"playwright_state_error_selector_{i+1}.png")


    if not active_keyword_search_selector or not keyword_search_box_element:
        print("Could not find a usable keyword search box after trying all selectors.")
        await page.screenshot(path="playwright_searchbox_not_found_after_loop.png") # Renamed for clarity
        print("Saved screenshot to playwright_searchbox_not_found_after_loop.png")
        return None

    print(f"Using keyword search box: {active_keyword_search_selector}")

    try:
        print(f"Clearing keyword search box: {active_keyword_search_selector}...")
        await keyword_search_box_element.clear(timeout=5000)
        print("Keyword search box cleared.")

        try:
            location_box_element = page.locator(location_search_box_selector).first
            if await location_box_element.is_visible(timeout=2000): # Simpler check if it's just for clearing
                print(f"Clearing location search box: {location_search_box_selector}...")
                await location_box_element.clear(timeout=5000)
                print("Location search box cleared.")
        except Exception:
            print(f"Notice: Could not clear location box ({location_search_box_selector}) or it's not present/interactable.")

        print(f"Filling search query: '{search_query}' into {active_keyword_search_selector}...")
        await keyword_search_box_element.fill(search_query)
        print(f"Search query filled into {active_keyword_search_selector}.")
        await page.wait_for_timeout(300)

        search_initiated = False
        search_button_selectors = [
            "button.jobs-search-box__submit-button",
            "button[data-control-name='search_jobs_button']",
            "form.jobs-search-box__form button[type='submit']",
            "button[aria-label*='Search jobs']:not([aria-label*='Clear'])",
            "//button[normalize-space()='Search' and contains(@class, 'jobs-search-box')]",
            "//button[normalize-space()='Search']"
        ]
        for i_btn, btn_selector in enumerate(search_button_selectors):
            try:
                print(f"Attempting to click search button with selector ({i_btn+1}): {btn_selector}")
                button_to_click = page.locator(btn_selector).first

                if await button_to_click.is_visible(timeout=3000) and await button_to_click.is_enabled(timeout=3000):
                    await button_to_click.click(timeout=5000)
                    print(f"Clicked search button: {btn_selector}")
                    search_initiated = True
                    break
                else:
                    print(f"Search button {btn_selector} found but not visible/enabled.")
            except Exception as e_btn_click:
                print(f"Search button {btn_selector} not found or error clicking: {e_btn_click}")


        if not search_initiated:
            print("No dedicated search button clicked. Pressing Enter in keyword search box.")
            try:
                await keyword_search_box_element.press("Enter")
                search_initiated = True
            except Exception as e_enter:
                print(f"Error pressing Enter: {e_enter}")
        
        if not search_initiated:
            print("Failed to initiate search.")
            await page.screenshot(path="playwright_search_initiation_fail.png")
            return None

    except Exception as e_search_interaction:
        print(f"Error during search interaction: {e_search_interaction}")
        await page.screenshot(path="playwright_search_interaction_error.png")
        return None

    # --- Wait for Search Results ---
    print("Waiting for search results to appear...")
    results_list_selectors = [
        "ul.jobs-search-results__list",
        "div.jobs-search-results-list",
        "section[aria-label*='job search results']"
    ]
    combined_results_selector = ", ".join(results_list_selectors)
    try:
        await page.wait_for_selector(combined_results_selector, state="visible", timeout=25000)
        print("Search results list detected.")
    except PlaywrightTimeoutError:
        print("Timeout: Search results list not detected after search submission.")
        await page.screenshot(path="playwright_search_results_timeout.png")
        return None
    except Exception as e_results_wait:
        print(f"Error waiting for search results: {e_results_wait}")
        await page.screenshot(path="playwright_search_results_error.png") # Generic error during results wait
        return None


    # This is a placeholder for your date filter and URL extraction logic
    # Ensure it's correctly placed and uses up-to-date selectors
    if date_filter_text:
        print(f"Attempting to apply date filter: {date_filter_text}")
        try:
            date_filter_button_selectors = [
                "button#searchFilter_timePostedRange",
                "button[aria-label='Date posted filter']",
                "//button[contains(.,'Date posted') and contains(@class, 'search-reusables__filter-pill-button')]"
            ]
            date_filter_button_clicked = False
            for selector in date_filter_button_selectors:
                try:
                    filter_button_locator = page.locator(selector).first
                    if await filter_button_locator.is_visible(timeout=5000) and await filter_button_locator.is_enabled(timeout=5000):
                        await filter_button_locator.click(timeout=7000)
                        date_filter_button_clicked = True
                        print(f"Clicked 'Date posted' filter button using selector: {selector}")
                        await page.wait_for_timeout(1500) 
                        break
                    else:
                        print(f"Date filter button {selector} not visible/enabled.")
                except Exception as e:
                    print(f"Date filter button selector {selector} failed: {e}")

            if date_filter_button_clicked:
                date_option_map = {
                    "Past 24 hours": "timePostedRange-r86400",
                    "Past week": "timePostedRange-r604800",
                    "Past month": "timePostedRange-r2592000"
                }
                option_id = date_option_map.get(date_filter_text)
                if option_id:
                    label_selector = f"label[for='{option_id}']"
                    await page.locator(label_selector).first.click(timeout=7000)
                    print(f"Selected date filter option: '{date_filter_text}'")
                    await page.wait_for_timeout(1000)
                    
                    apply_button_selectors = [
                        "//div[contains(@class, 'reusable-search-filters-buttons')]//button[contains(@class, 'artdeco-button--primary') and (normalize-space()='Show results' or normalize-space()='Apply')]",
                        "button[data-control-name='filter_submit_button']",
                        "button.filters-button-bottom-sheet__submit-button"
                    ]
                    apply_clicked = False
                    for apply_selector in apply_button_selectors:
                        try:
                            apply_button_locator = page.locator(apply_selector).first
                            if await apply_button_locator.is_visible(timeout=5000) and await apply_button_locator.is_enabled(timeout=5000):
                                await apply_button_locator.click(timeout=7000)
                                apply_clicked = True
                                print(f"Clicked 'Apply' button for date filter using selector: {apply_selector}")
                                await page.wait_for_load_state('networkidle', timeout=60000)
                                break
                            else:
                                print(f"Apply button {apply_selector} not visible/enabled.")
                        except Exception as e:
                            print(f"Apply button selector {apply_selector} failed: {e}")
                    if not apply_clicked:
                        print("Could not click apply button for date filter. Proceeding without it or it applied automatically.")
                        await page.keyboard.press("Escape", delay=200) 
                        await page.wait_for_load_state('networkidle', timeout=30000)
                else:
                    print(f"Date filter option '{date_filter_text}' not recognized. Closing dropdown.")
                    await page.keyboard.press("Escape") 
            else:
                print("Could not click 'Date posted' filter button.")
        except Exception as e:
            print(f"Error applying date filter: {e}. Proceeding without it.")
        
        print("Proceeding after date filter attempt. Waiting for network idle if changes occurred...")
        await page.wait_for_load_state('networkidle', timeout=60000)


    print("Extracting first job URL from search results...")
    job_card_link_selectors = [
        "ul.jobs-search-results__list > li.jobs-search-results__list-item a.job-card-list__title[href*='/jobs/view/']",
        "li.jobs-search-results__list-item a[href*='/jobs/view/']",
        "div.job-search-card a[href*='/jobs/view/']",
        "li.scaffold-layout__list-item a[href*='/jobs/view/']"
    ]
    first_job_url = None
    for i_link, link_selector in enumerate(job_card_link_selectors):
        try:
            print(f"Trying to find job link with selector ({i_link+1}): {link_selector}")
            job_links = await page.locator(link_selector).all()
            if not job_links: continue
            
            print(f"Found {len(job_links)} potential job links with selector: {link_selector}")
            link_element = job_links[0]
            href = await link_element.get_attribute("href")
            if href:
                match = re.search(r'/jobs/view/(\d+)', href)
                if match:
                    job_id = match.group(1)
                    first_job_url = f"https://www.linkedin.com/jobs/view/{job_id}"
                    print(f"Found and cleaned first job URL: {first_job_url}")
                    return first_job_url
        except Exception as e_link_extract:
            print(f"Error processing job links with selector {link_selector}: {e_link_extract}")

    if not first_job_url:
        print("Could not find any job URL from the search results.")
        await page.screenshot(path="playwright_job_url_extraction_fail.png")
    return first_job_url


async def main():
    try:
        with open("lite_linkedin_bot/config.yaml", 'r') as f: # Ensure this path is correct
            config = yaml.safe_load(f)
    except FileNotFoundError:
        print("Error: config.yaml not found. Place it in a 'lite_linkedin_bot' subdirectory or adjust path.")
        return
    except Exception as e:
        print(f"Error reading config.yaml: {e}")
        return

    email = config.get("email")
    password = config.get("password")
    search_query = config.get("search_query", "python developer united states easy apply remote")
    date_filter = config.get("date_filter") # e.g., "Past 24 hours", "Past week", "Past month" or None


    if not email or not password:
        print("Error: Email or password not found in config.yaml.")
        return

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, args=['--start-maximized'])
        context = await browser.new_context(no_viewport=True) 
        page = await context.new_page()

        try:
            print("Navigating to LinkedIn login page...")
            await page.goto("https://www.linkedin.com/login", timeout=60000)

            print("Entering credentials...")
            await page.fill("input#username", email, timeout=10000)
            await page.fill("input#password", password, timeout=10000)
            await page.click("button[type='submit']", timeout=10000)
            print("Login submitted.")

            try:
                await page.wait_for_url("**/feed/**", timeout=30000)
                print("Login successful. Navigated to feed.")
            except PlaywrightTimeoutError:
                print("Login may have failed or requires verification. Check the browser.")
                current_url = page.url
                if "checkpoint" in current_url or "challenge" in current_url:
                    print(f"Security checkpoint detected at {current_url}. Please solve it manually in the browser.")
                    print("Script will wait for 60 seconds for manual intervention.")
                    await page.wait_for_timeout(60000) 
                    if "feed" not in page.url and "jobs" not in page.url and not "linkedin.com/login" in page.url: # Check again
                         print("Still not on feed or jobs page after manual intervention. Exiting.")
                         if browser.is_connected(): await browser.close()
                         return
                    print("Resuming after manual intervention.")
                else:
                    print(f"Not on feed page, current URL: {page.url}. Login might have failed. Check screenshot if any.")
                    await page.screenshot(path="playwright_login_fail_nocheckpoint.png")
                    if "linkedin.com/login" in page.url:
                        print("Still on login page. Exiting.")
                        if browser.is_connected(): await browser.close()
                        return


            job_url_to_apply = await get_job_url_from_search(page, search_query, date_filter)

            if not job_url_to_apply:
                print("Failed to get a job URL from search. Exiting.")
                if browser.is_connected(): await browser.close()
                return

            print(f"Navigating to job page: {job_url_to_apply}")
            await page.goto(job_url_to_apply, timeout=60000, wait_until="domcontentloaded")
            print("Job page loaded.")

            easy_apply_button_selectors = [
                "button.jobs-apply-button--top-card",
                "div.jobs-unified-top-card__primary-actions button.jobs-apply-button", 
                "button:has-text('Easy Apply')", 
                "//button[contains(normalize-space(.), 'Easy Apply')]", 
                "//button[contains(@aria-label, 'Easy Apply') or contains(@aria-label, 'Apply now')]"
            ]
            easy_apply_clicked = False
            for selector in easy_apply_button_selectors:
                try:
                    print(f"Attempting to click Easy Apply button with selector: {selector}")
                    button_locator = page.locator(selector).first 
                    
                    await button_locator.scroll_into_view_if_needed(timeout=5000)
                    if await button_locator.is_visible(timeout=3000) and await button_locator.is_enabled(timeout=3000):
                        await button_locator.click(timeout=10000)
                        easy_apply_clicked = True
                        print("Easy Apply button clicked.")
                        break
                    else:
                        print(f"Easy Apply button ({selector}) found but not visible/enabled.")
                except PlaywrightTimeoutError:
                    print(f"Easy Apply button not found or not clickable with selector (Timeout): {selector}")
                except Exception as e:
                    print(f"Error clicking Easy Apply button with selector {selector}: {e}")
            
            if not easy_apply_clicked:
                print("Failed to click the Easy Apply button after trying all selectors.")
                await page.screenshot(path="playwright_easyapply_button_fail.png")
                if browser.is_connected(): await browser.close()
                return

            print("Waiting for Easy Apply modal to appear...")
            modal_selector = "div.jobs-easy-apply-modal__content" 
            try:
                await page.wait_for_selector(modal_selector, state="visible", timeout=30000)
                print("Easy Apply modal is visible.")
                await page.wait_for_timeout(2000) 
                dom_content = await page.content()
                output_file = "easy_apply_modal_dom.html"
                with open(output_file, "w", encoding="utf-8") as f:
                    f.write(dom_content)
                print(f"Live DOM (including modal) saved to {output_file}")

            except PlaywrightTimeoutError:
                print(f"Timeout waiting for Easy Apply modal ({modal_selector}) to become visible.")
                dom_content_on_fail = await page.content()
                output_file_fail = "easy_apply_modal_fail_dom.html"
                with open(output_file_fail, "w", encoding="utf-8") as f:
                    f.write(dom_content_on_fail)
                print(f"DOM at the point of modal timeout saved to {output_file_fail}")
            except Exception as e:
                print(f"An error occurred while waiting for modal or dumping DOM: {e}")

        except Exception as e:
            print(f"An error occurred in the main process: {e}")
            if browser.is_connected() and not page.is_closed():
                 await page.screenshot(path="playwright_error_screenshot.png")
                 print("Saved screenshot to playwright_error_screenshot.png")

        finally:
            print("Closing browser...")
            if browser.is_connected(): 
                await browser.close()

if __name__ == "__main__":
    print("Script starting. Ensure config.yaml is present and you have run 'playwright install'.")
    asyncio.run(main())
