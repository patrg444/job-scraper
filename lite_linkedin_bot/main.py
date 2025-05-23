import argparse
import logging
import time
import csv
import os
import random
from datetime import datetime
import yaml
from auto_apply_bot.linkedin_bot import EasyApplyBot
from auto_apply_bot.searcher import Searcher
from auto_apply_bot.resume_job_aligner import run_alignment_for_job # Added import
from selenium.webdriver.common.by import By
from selenium.common.exceptions import TimeoutException, NoSuchElementException

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('linkedin_bot.log', mode='w'), # Log to a file, overwrite each time
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

def load_answers(answers_path):
    """Loads form answers from a YAML file."""
    try:
        with open(answers_path, 'r') as f:
            answers = yaml.safe_load(f)
        logger.info(f"Loaded form answers from {answers_path}")
        return answers
    except FileNotFoundError:
        logger.error(f"File not found: {answers_path}")
        return None
    except yaml.YAMLError as e:
        logger.error(f"Error parsing YAML file: {e}")
        return None

def test_pagination_navigation(config):
    logger.info("--- Starting Pagination Navigation Test ---")
    email = config.get('email')
    password = config.get('password')
    resume_path = config.get('resume_path') # Needed for bot init, though not used in this test
    
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

    date_filter = config.get('date_filter', 'Past week')
    
    # Initialize bot (needed for driver and login)
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
        results_dir = f"results_pagination_test_{timestamp}"
        os.makedirs(results_dir, exist_ok=True)
        logger.info(f"Created results directory for pagination test: {results_dir}")
        # Pass results_dir to searcher if it needs it for saving debug files
        searcher = Searcher(bot.driver, bot.wait)
        searcher.results_dir = results_dir # Ensure searcher can save debug files

        # Perform the initial search to get to the results page
        # Using the first query from the config for this test
        query_config = search_queries_config[0]
        query = query_config.get('query')
        location = query_config.get('location', '')
        full_query = f"{query} {location}".strip()

        logger.info(f"Performing initial search for query: {full_query}")
        searcher.driver.get("https://www.linkedin.com/jobs/")
        searcher._random_delay(2,4)
        try:
            search_box = searcher.wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "input.jobs-search-box__text-input")))
            search_box.clear()
            for char_s in full_query:
                search_box.send_keys(char_s)
                time.sleep(0.05 + random.random() * 0.1)
            searcher._random_delay(0.5, 1.5)
            search_box.send_keys(Keys.ENTER)
        except (TimeoutException, NoSuchElementException) as e_search_box:
            logger.error(f"Failed to find and fill search box: {e_search_box}")
            return
        
        searcher._random_delay(3, 5)
        if date_filter:
            searcher._apply_date_filter(date_filter)
            searcher._random_delay(2, 3)

        # Pagination loop
        max_page_attempts = 10  # Try to navigate a few pages
        for i in range(max_page_attempts):
            logger.info(f"--- Attempting to navigate to page {i + 2} ---")
            
            # Ensure page is scrolled down before trying to find next button
            logger.info("Scrolling to the bottom of the page before pagination attempt.")
            searcher.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(1.5) # Allow time for elements to load/become interactable

            # Try to get current page number text
            try:
                page_state_element = searcher.driver.find_element(By.CSS_SELECTOR, "p.jobs-search-pagination__page-state")
                current_page_text = page_state_element.text
                logger.info(f"Current pagination state: {current_page_text}")
            except NoSuchElementException:
                logger.warning("Could not find current page state element.")
            except Exception as e_page_state:
                logger.error(f"Error getting page state: {e_page_state}")

            success = searcher._go_to_next_page()
            if success:
                logger.info(f"Successfully navigated to next page (Attempt {i + 1}).")
                searcher._random_delay(3, 5) # Wait for new page content to load
            else:
                logger.warning(f"Failed to navigate to next page or no more pages (Attempt {i + 1}).")
                # Debug HTML is saved by _go_to_next_page on failure
                break
        
        logger.info("--- Pagination Navigation Test Finished ---")

    except Exception as e:
        logger.error(f"An error occurred during pagination test: {e}", exc_info=True)
    finally:
        if bot and bot.driver:
            bot.close()

def run_bot(config, answers):
    """Initializes and runs the bot for applying or collecting job info."""
    results_dir = "" 
    applications_csv_path = ""
    questions_csv_path = ""
    job_details_csv_path = ""
    all_urls = [] 
    successful_collections = 0

    email = config.get('email')
    password = config.get('password')
    resume_path = config.get('resume_path')
    job_urls_config = config.get('job_urls', [])
    
    # Construct path to cline_parsed_resume.json relative to this script's directory
    current_script_dir = os.path.dirname(os.path.abspath(__file__))
    parsed_resume_json_path = os.path.join(current_script_dir, "..", "cline_parsed_resume.json")
    logger.info(f"Resume JSON path for alignment resolved to: {parsed_resume_json_path}")
    
    search_query_singular = config.get('search_query')
    search_queries_plural = config.get('search_queries')

    if search_query_singular and not search_queries_plural:
        search_queries_config = [{'query': search_query_singular, 'location': ''}]
        logger.info(f"Using singular 'search_query' from config: {search_query_singular}")
    elif search_queries_plural:
        search_queries_config = search_queries_plural
        logger.info("Using 'search_queries' list from config.")
    else:
        search_queries_config = []
        logger.info("No 'search_query' or 'search_queries' found in config.")

    date_filter = config.get('date_filter', 'Past week')
    max_links_to_collect = config.get('max_links', 20)
    pages_to_scan_config = config.get('pages_to_scan', 3) # Load pages_to_scan from config, default to 3 if not present
    
    openai_api_key = config.get('openai_api_key')
    use_llm_for_answers = config.get('use_llm', False)
    skip_if_applied_setting = config.get('skip_if_applied', True)

    config_apply_to_jobs = config.get('apply_to_jobs', False)
    config_collect_questions = config.get('collect_questions', True)
    config_collect_job_details = config.get('collect_job_details', True)

    if not all([email, password, resume_path]):
        logger.error("Email, password, or resume path missing in config.")
        return

    bot = EasyApplyBot(email, password, resume_path, form_answers=answers, openai_api_key=openai_api_key, use_llm=use_llm_for_answers, skip_if_applied_override=skip_if_applied_setting)
    
    try:
        bot._init_driver()
        if not bot.driver:
            logger.error("WebDriver initialization failed. Exiting.")
            return

        if not bot.login():
            logger.error("Login failed. Exiting.")
            return
        logger.info("Login successful.")

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        results_dir = f"results_{timestamp}"
        os.makedirs(results_dir, exist_ok=True)
        logger.info(f"Created results directory: {results_dir}")
        bot.results_dir = results_dir 
        
        # Pass results_dir to searcher instance
        searcher = Searcher(bot.driver, bot.wait)
        searcher.results_dir = results_dir


        applications_csv_path = os.path.join(results_dir, "applications.csv")
        questions_csv_path = os.path.join(results_dir, "application_questions.csv")
        job_details_csv_path = os.path.join(results_dir, "job_details.csv")

        searched_urls = []
        if search_queries_config:
            for query_config_item in search_queries_config:
                query = query_config_item.get('query')
                location = query_config_item.get('location', '')
                if query:
                    full_query = f"{query} {location}".strip()
                    logger.info(f"Searching for jobs with query: {full_query}, pages_to_scan from config: {pages_to_scan_config}")
                    query_urls = searcher.search_jobs(
                        full_query, 
                        date_filter=date_filter, 
                        pages_to_scan=pages_to_scan_config,  # Pass the loaded config value
                        max_links=max_links_to_collect
                    )
                    if query_urls:
                        searched_urls.extend(query_urls)
                        logger.info(f"Found {len(query_urls)} jobs for query: '{full_query}' after scanning up to {pages_to_scan_config} pages.")
                    else:
                        logger.info(f"No jobs found for query: '{full_query}'")
                else:
                    logger.warning("Empty search query found in config. Skipping.")
            
            if searched_urls is None: searched_urls = []
            
            search_csv_path = os.path.join(results_dir, "search_results.csv")
            with open(search_csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["Job URL"])
                for url_item in searched_urls:
                    writer.writerow([url_item])
            logger.info(f"Search results saved to {search_csv_path}")
        else:
            logger.info("No search queries provided in config. Using only job_urls if available.")

        job_urls_config = job_urls_config or [] 
        all_urls = list(set(job_urls_config + searched_urls))

        if not all_urls:
            logger.info("No job URLs to process (neither provided in config nor found via search). Exiting.")
            return

        # For this test run, process up to 75 jobs to get a larger sample
        max_jobs_for_this_test_run = 75 
        if len(all_urls) > max_jobs_for_this_test_run:
            logger.info(f"Limiting total job processing from {len(all_urls)} to {max_jobs_for_this_test_run} for this test run.")
            all_urls = all_urls[:max_jobs_for_this_test_run]
        elif max_links_to_collect == 0: # This condition might still be relevant if we want to process truly ALL links from config
            logger.info(f"'max_links' (from config, used by Searcher per page) is 0, but main loop will process up to {len(all_urls)} or {max_jobs_for_this_test_run}.")
        
        logger.info(f"Preparing to process {len(all_urls)} jobs.")
        
        with open(applications_csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["Job URL", "Status"])
        
        if config_collect_questions:
            with open(questions_csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["Job URL", "Company", "Question Label", "Input Type", "Options", "Is Required"])

        if config_collect_job_details:
            with open(job_details_csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow([
                    "Job URL", "Application Link", "Company Name", "Job Title", "Location",
                    "Employment Type", "Required Experience (Years)", "Required Education",
                    "Required Skills", "Mention Keywords", "Description Summary"
                ])

        successful_collections = 0
        for i, current_url in enumerate(all_urls):
            logger.info(f"\nProcessing job {i+1} of {len(all_urls)}: {current_url}")
            try:
                if config_collect_job_details:
                    logger.info(f"Collecting job details for {current_url}")
                    job_details = bot.collect_job_details(current_url)
                    if job_details:
                        with open(job_details_csv_path, "a", newline="", encoding="utf-8") as f:
                            writer = csv.writer(f)
                            writer.writerow([
                                job_details.get("job_url", ""),
                                job_details.get("application_link", ""),
                                job_details.get("company_name", ""),
                                job_details.get("job_title", ""),
                                job_details.get("location", ""),
                                job_details.get("employment_type", ""),
                                job_details.get("required_experience_years", ""),
                                job_details.get("required_education", ""),
                                "; ".join(job_details.get("required_skills", [])),
                                str(job_details.get("mention_keywords", "")),
                                job_details.get("description_summary", "")
                            ])
                        logger.info(f"Collected job details for {current_url}")
                        successful_collections += 1

                        # Generate and print resume-job alignment report
                        logger.info(f"Generating alignment report for {current_url} using {parsed_resume_json_path}")
                        alignment_report = run_alignment_for_job(parsed_resume_json_path, job_details)
                        if alignment_report:
                            logger.info(f"\n--- Resume-Job Alignment Report for {current_url} ---")
                            logger.info(f"Job Title: {alignment_report.get('job_title')} at {alignment_report.get('company_name')}")
                            
                            skill_comp_report = alignment_report.get('skill_comparison', {})
                            logger.info("\n[Skill Comparison]")
                            for key, val in skill_comp_report.items():
                                logger.info(f"  {key.replace('_', ' ').title()}: {', '.join(val) if val else 'None'}")
                            
                            exp_comp_report = alignment_report.get('experience_comparison', {})
                            logger.info("\n[Experience Comparison]")
                            logger.info(f"  Resume Stated Years: {exp_comp_report.get('resume_stated_years')}")
                            logger.info(f"  Job Required Years: {exp_comp_report.get('job_required_years')}")
                            logger.info(f"  Match Status: {exp_comp_report.get('match_status')}")

                            edu_comp_report = alignment_report.get('education_comparison', {})
                            logger.info("\n[Education Comparison]")
                            logger.info(f"  Resume Degrees: {', '.join(edu_comp_report.get('resume_education_levels_achieved', []))}")
                            logger.info(f"  Job Required Education: {edu_comp_report.get('job_required_education_text')}")
                            logger.info(f"  Match Status: {edu_comp_report.get('match_status')}")
                            
                            kw_analysis_report = alignment_report.get('keyword_analysis', {})
                            logger.info("\n[Keyword Analysis]")
                            logger.info(f"  Job Keywords Found in Resume: {', '.join(kw_analysis_report.get('job_mention_keywords_found_in_resume',[])) if kw_analysis_report.get('job_mention_keywords_found_in_resume') else 'None'}")
                            logger.info(f"  Job Keywords Missing from Resume: {', '.join(kw_analysis_report.get('job_mention_keywords_missing_from_resume',[])) if kw_analysis_report.get('job_mention_keywords_missing_from_resume') else 'None'}")

                            logger.info("\n[Overall Summary & Suggestions]")
                            for suggestion in alignment_report.get('overall_summary_and_suggestions', []):
                                logger.info(f"  - {suggestion}")
                            logger.info("--- End of Alignment Report ---")
                        else:
                            logger.warning(f"Could not generate alignment report for {current_url}. Check for errors from run_alignment_for_job.")
                    else:
                        logger.info(f"No job details collected or error during collection for {current_url}")

                elif config_collect_questions:
                    logger.info(f"Collecting questions for {current_url} (not applying)")
                    collected_questions = bot.collect_application_questions(current_url)
                    if collected_questions:
                        with open(questions_csv_path, "a", newline="", encoding="utf-8") as f:
                            writer = csv.writer(f)
                            for q_data in collected_questions:
                                writer.writerow([
                                    q_data["job_url"], q_data["company"], q_data["question_label"],
                                    q_data["input_type"], q_data.get("options", ""), q_data.get("is_required", False)
                                ])
                        logger.info(f"Collected {len(collected_questions)} questions for {current_url}")
                        successful_collections += 1
                    else:
                        logger.info(f"No questions collected or error during collection for {current_url}")
                
                elif config_apply_to_jobs:
                    logger.info(f"Attempting to apply to {current_url}")
                    status = bot.apply_to_job(current_url)
                    with open(applications_csv_path, "a", newline="", encoding="utf-8") as f:
                        writer = csv.writer(f)
                        writer.writerow([current_url, "Applied" if status else "Failed/Skipped"])
                else:
                    logger.info(f"Skipping {current_url} as apply_to_jobs, collect_questions, and collect_job_details are all false.")
            except Exception as e_job_proc:
                logger.error(f"Error processing URL {current_url}: {e_job_proc}", exc_info=True)
                if config_apply_to_jobs and not config_collect_questions and not config_collect_job_details:
                    with open(applications_csv_path, "a", newline="", encoding="utf-8") as f:
                        writer = csv.writer(f)
                        writer.writerow([current_url, f"Error: {e_job_proc}"])
            time.sleep(random.uniform(5, 10)) 
    except Exception as e_main:
        logger.error(f"An unexpected error occurred in run_bot: {e_main}", exc_info=True)
    finally:
        if bot and bot.driver:
            bot.close()
        if config_collect_job_details:
            logger.info(f"\nJob details collection process finished. Details saved to {job_details_csv_path}")
        elif config_collect_questions:
            logger.info(f"\nQuestion collection process finished. Detailed questions saved to {questions_csv_path}")
        elif config_apply_to_jobs:
            logger.info(f"\nApplication process finished. Results saved to {applications_csv_path}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="LinkedIn Easy Apply Bot")
    
    # Get the directory of the current script
    script_dir = os.path.dirname(os.path.abspath(__file__))
    
    default_config_name = "config.yaml"
    default_answers_name = "form_answers.yaml"
    
    parser.add_argument("--config", type=str, default=default_config_name, help="Path to the configuration YAML file.")
    parser.add_argument("--answers", type=str, default=default_answers_name, help="Path to the form answers YAML file.")
    parser.add_argument("--test_pagination", action="store_true", help="Run only the pagination navigation test.")
    args = parser.parse_args()

    config_file_path = args.config
    if args.config == default_config_name and not os.path.isabs(args.config):
        config_file_path = os.path.join(script_dir, args.config)
        logger.info(f"Config path resolved to: {config_file_path}")

    answers_file_path = args.answers
    if args.answers == default_answers_name and not os.path.isabs(args.answers):
        answers_file_path = os.path.join(script_dir, args.answers)
        logger.info(f"Answers path resolved to: {answers_file_path}")
        
    config_data = load_config(config_file_path)
    if not config_data:
        logger.error("Failed to load configuration. Exiting.")
    else:
        if args.test_pagination:
            test_pagination_navigation(config_data)
        else:
            answers_data = load_answers(answers_file_path)
            if answers_data:
                run_bot(config_data, answers_data)
            else:
                logger.error("Failed to load answers. Exiting normal run.")
