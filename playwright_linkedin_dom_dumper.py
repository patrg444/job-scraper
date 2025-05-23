import asyncio
import yaml
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
import re # For cleaning job URLs and extracting job ID
import argparse # For command-line arguments
import os # For directory creation and path joining

# This script uses Playwright to log into LinkedIn, navigate to a specific job page,
# click the "Easy Apply" button, and then dump the full HTML of the page
# once the Easy Apply modal is presumed to be visible.

# Command-line arguments control the target job URL and the output directory.
#   --job-url (-u): The full LinkedIn job URL to process. This is required.
#   --output-dir (-o): Directory where the HTML dump will be saved.
#                      Defaults to "modal_html_dumps".

# The output HTML filename is determined by the job ID extracted from the job URL:
#   <output-dir>/easy_apply_modal_<job_id>.html
# If the job ID cannot be extracted, "unknown_job_id" is used.

# Removed get_job_url_from_search function as it's no longer needed.

async def main(args): # args parameter now comes from argparse
    try:
        # Configuration for login details is still loaded from config.yaml
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
    # search_query and date_filter are no longer read here as the job URL is provided via CLI.

    if not email or not password:
        print("Error: Email or password not found in config.yaml.")
        return

    job_url_to_apply = args.job_url # Use job_url from parsed command-line arguments

    # Extract Job ID from the provided URL to use in the output filename.
    job_id_match = re.search(r'/jobs/view/(\d+)/', job_url_to_apply)
    if job_id_match:
        job_id = job_id_match.group(1)
    else:
        job_id = "unknown_job_id" # Fallback if ID extraction fails
        print(f"Warning: Could not extract job ID from URL: {job_url_to_apply}. Using fallback: {job_id}")


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
            
            # Removed call to get_job_url_from_search
            # job_url_to_apply is now directly from args.job_url

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

                # Create the specified output directory if it doesn't exist.
                os.makedirs(args.output_dir, exist_ok=True)
                
                # Construct the output filename using the extracted job_id.
                # Example: "modal_html_dumps/easy_apply_modal_1234567890.html"
                output_filename = f"easy_apply_modal_{job_id}.html"
                output_path = os.path.join(args.output_dir, output_filename)

                with open(output_path, "w", encoding="utf-8") as f:
                    f.write(dom_content) # Save the full page DOM.
                print(f"Live DOM (including modal) saved to {output_path}")

            except PlaywrightTimeoutError:
                print(f"Timeout waiting for Easy Apply modal ({modal_selector}) to become visible.")
                dom_content_on_fail = await page.content()
                
                # Save failure dump to the specified output directory as well.
                # Filename indicates failure and includes job_id.
                os.makedirs(args.output_dir, exist_ok=True)
                output_filename_fail = f"easy_apply_modal_fail_dom_{job_id}.html"
                output_path_fail = os.path.join(args.output_dir, output_filename_fail)

                with open(output_path_fail, "w", encoding="utf-8") as f:
                    f.write(dom_content_on_fail)
                print(f"DOM at the point of modal timeout saved to {output_path_fail}")
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
    # Setup for command-line argument parsing.
    parser = argparse.ArgumentParser(description="Dump LinkedIn Easy Apply modal DOM for a given job URL.")
    parser.add_argument("--job-url", "-u", type=str, required=True, 
                        help="The full LinkedIn job URL to process.")
    parser.add_argument("--output-dir", "-o", type=str, default="modal_html_dumps", 
                        help="Directory to save the HTML dump. Defaults to 'modal_html_dumps'.")
    
    cli_args = parser.parse_args() # Parse arguments from the command line.

    print(f"Script starting. Job URL: {cli_args.job_url}, Output Dir: {cli_args.output_dir}")
    print("Ensure config.yaml (for login credentials) is present in 'lite_linkedin_bot/' directory and you have run 'playwright install'.")
    asyncio.run(main(cli_args)) # Pass parsed arguments to the main async function.
