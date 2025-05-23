import csv
import os
from bs4 import BeautifulSoup # Requires: pip install beautifulsoup4
import argparse
import re

def get_job_id_from_url(job_url: str) -> str:
    """Extracts the job ID from a LinkedIn job URL."""
    match = re.search(r'/jobs/view/(\d+)', job_url)
    if match:
        return match.group(1)
    # Fallback for URLs that might already be just an ID or different format
    match_direct_id = re.search(r'(\d+)', job_url)
    if match_direct_id:
        return match_direct_id.group(1)
    return ""

def load_job_data_from_csv(csv_filepath, target_job_url_or_id):
    """Loads a specific job's data from the job_details.csv file."""
    target_id = get_job_id_from_url(target_job_url_or_id)
    if not target_id:
        print(f"Could not extract a valid job ID from '{target_job_url_or_id}'")
        return None

    try:
        with open(csv_filepath, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                row_job_id = get_job_id_from_url(row.get('Job URL', ''))
                if row_job_id == target_id:
                    print(f"Found job data for ID {target_id} in CSV.")
                    return row
    except FileNotFoundError:
        print(f"Error: CSV file not found at {csv_filepath}")
        return None
    except Exception as e:
        print(f"Error reading CSV: {e}")
        return None
    print(f"Job ID {target_id} not found in {csv_filepath}")
    return None

def compare_main_job_page(job_data, html_content_main_page):
    """
    Compares data from job_details.csv with the content of the main job page HTML.
    This is a basic example; you'll need to tailor selectors to the actual HTML structure.
    """
    if not job_data:
        print("No job data provided for main page comparison.")
        return

    print("\n--- Comparing with Main Job Page HTML ---")
    soup = BeautifulSoup(html_content_main_page, 'html.parser')

    # Example 1: Compare Job Title
    parsed_title = job_data.get('Job Title', 'N/A')
    # Common selectors for job titles - these will likely need adjustment!
    # Based on lite_linkedin_bot's _get_job_title_from_top_card
    title_selectors_html = [
        "h1.t-24.t-bold.jobs-unified-top-card__job-title",
        "h1.topcard__title",
        "h1.job-details-jobs-unified-top-card__job-title" # More specific one from recent logs
    ]
    html_title_found = "Not found in HTML"
    for selector in title_selectors_html:
        title_element = soup.select_one(selector)
        if title_element:
            html_title_found = title_element.get_text(strip=True)
            break
    
    print(f"Job Title (CSV): {parsed_title}")
    print(f"Job Title (HTML): {html_title_found}")
    if parsed_title.lower() == html_title_found.lower():
        print("Job Title: MATCH")
    else:
        print("Job Title: MISMATCH or HTML structure changed")

    # Example 2: Compare Company Name
    parsed_company = job_data.get('Company Name', 'N/A')
    # Based on lite_linkedin_bot's _get_company_name_from_top_card
    company_selectors_html = [
        "span.jobs-unified-top-card__company-name a",
        "span.jobs-unified-top-card__company-name",
        ".topcard__org-name-link",
        "a[data-tracking-control-name='public_jobs_topcard_org_name']",
        "div.job-details-jobs-unified-top-card__primary-description-container a[href*='/company/']"
    ]
    html_company_found = "Not found in HTML"
    for selector in company_selectors_html:
        company_element = soup.select_one(selector)
        if company_element:
            html_company_found = company_element.get_text(strip=True)
            break
            
    print(f"Company Name (CSV): {parsed_company}")
    print(f"Company Name (HTML): {html_company_found}")
    if parsed_company.lower() in html_company_found.lower() or html_company_found.lower() in parsed_company.lower():
        print("Company Name: MATCH (approximate)")
    else:
        print("Company Name: MISMATCH or HTML structure changed")

    # Example 3: Check for presence of a specific required skill (example)
    # This is more complex as skills are a list and their representation in HTML can vary.
    parsed_skills_str = job_data.get('Required Skills', '')
    if parsed_skills_str:
        parsed_skills_list = [s.strip() for s in parsed_skills_str.split(';') if s.strip()]
        if parsed_skills_list:
            example_skill_to_check = parsed_skills_list[0] # Check the first skill
            print(f"Checking for skill (from CSV): {example_skill_to_check}")
            # This is a very generic check. In reality, skills are often in lists (ul/li)
            # or within specific sections.
            job_description_area = soup.select_one("div.jobs-description-content__text") or \
                                   soup.select_one("div.show-more-less-html__markup") or \
                                   soup.select_one("div#job-details")
                                   
            if job_description_area and example_skill_to_check.lower() in job_description_area.get_text().lower():
                print(f"Skill '{example_skill_to_check}': FOUND in job description HTML.")
            elif job_description_area:
                print(f"Skill '{example_skill_to_check}': NOT FOUND in job description HTML body.")
            else:
                print(f"Skill '{example_skill_to_check}': Job description area not found in HTML for skill check.")
        else:
            print("No required skills listed in CSV to check.")
    else:
        print("No 'Required Skills' column or data in CSV.")

    print("--- Main Job Page Comparison Done ---")


def compare_easy_apply_modal(html_content_modal):
    """
    Analyzes the content of an Easy Apply modal HTML.
    This is a basic example; you'll need to tailor selectors.
    """
    print("\n--- Comparing with Easy Apply Modal HTML ---")
    soup = BeautifulSoup(html_content_modal, 'html.parser')

    # Example 1: Look for form elements (e.g., input fields, labels)
    # This is highly dependent on LinkedIn's current modal structure.
    # The selectors used by lite_linkedin_bot FormHandler would be a good starting point.
    
    # Look for question labels (often <label> or <legend>)
    question_labels = soup.select("label.artdeco-form-item-label, legend.fb-form-element-label")
    if question_labels:
        print(f"Found {len(question_labels)} potential question labels in the modal:")
        for i, label in enumerate(question_labels[:3]): # Print first 3
            print(f"  Modal Question Label {i+1}: {label.get_text(strip=True)}")
    else:
        print("No typical question labels found in modal HTML (using example selectors).")

    # Look for input fields
    input_fields = soup.select("input.artdeco-text-input--input, input.fb-single-line-text__input")
    if input_fields:
        print(f"Found {len(input_fields)} potential text input fields in the modal:")
        for i, input_el in enumerate(input_fields[:3]):
            input_name = input_el.get('name', 'N/A')
            input_id = input_el.get('id', 'N/A')
            print(f"  Modal Input {i+1}: ID='{input_id}', Name='{input_name}'")
    else:
        print("No typical text input fields found in modal HTML (using example selectors).")
        
    # Look for select (dropdown) fields
    select_fields = soup.select("select.artdeco-dropdown__select, select.fb-dropdown__select")
    if select_fields:
        print(f"Found {len(select_fields)} potential dropdown (select) fields in the modal:")
        for i, select_el in enumerate(select_fields[:3]):
            select_name = select_el.get('name', 'N/A')
            select_id = select_el.get('id', 'N/A')
            print(f"  Modal Select {i+1}: ID='{select_id}', Name='{select_name}'")
    else:
        print("No typical dropdown (select) fields found in modal HTML (using example selectors).")

    # You would then compare these findings with data you expect to be parsed from the modal.
    # For example, if you ran `collect_application_questions` and it saved questions to a CSV,
    # you would load that CSV and compare the labels/input types.

    print("--- Easy Apply Modal Comparison Done ---")


def main():
    parser = argparse.ArgumentParser(description="Compare parsed job data with archived HTML.")
    parser.add_argument("--job-url-or-id", required=True, help="The LinkedIn job URL or just the job ID to compare.")
    parser.add_argument("--csv-file", required=True, help="Path to the job_details.csv file generated by lite_linkedin_bot.")
    parser.add_argument("--results-dir", required=True, help="Path to the main results directory (e.g., 'results_YYYYMMDD_HHMMSS') where lite_linkedin_bot saved its output.")
    parser.add_argument("--modal-html-dir", help="Path to the directory where Easy Apply modal HTML files are stored (e.g., 'modal_html_dumps' used by playwright_linkedin_dom_dumper.py).")

    args = parser.parse_args()

    job_data = load_job_data_from_csv(args.csv_file, args.job_url_or_id)

    if not job_data:
        print(f"Could not find or load data for job '{args.job_url_or_id}' from {args.csv_file}.")
        return

    # --- Main Job Page Comparison ---
    main_page_html_relative_path = job_data.get("HTML File Path")
    if main_page_html_relative_path:
        # Construct absolute path if results_dir is provided
        main_page_html_full_path = os.path.join(args.results_dir, main_page_html_relative_path)
        try:
            with open(main_page_html_full_path, 'r', encoding='utf-8') as f:
                html_content_main = f.read()
            compare_main_job_page(job_data, html_content_main)
        except FileNotFoundError:
            print(f"Error: Main job page HTML file not found at {main_page_html_full_path}")
        except Exception as e:
            print(f"Error reading main job page HTML file: {e}")
    else:
        print("No 'HTML File Path' found in CSV for this job. Skipping main page comparison.")

    # --- Easy Apply Modal Comparison ---
    if args.modal_html_dir:
        job_id = get_job_id_from_url(args.job_url_or_id)
        if job_id:
            modal_html_filename = f"easy_apply_modal_{job_id}.html"
            modal_html_full_path = os.path.join(args.modal_html_dir, modal_html_filename)
            try:
                with open(modal_html_full_path, 'r', encoding='utf-8') as f:
                    html_content_modal = f.read()
                compare_easy_apply_modal(html_content_modal)
            except FileNotFoundError:
                print(f"Info: Easy Apply modal HTML file not found at {modal_html_full_path}. Skipping modal comparison for this job.")
            except Exception as e:
                print(f"Error reading Easy Apply modal HTML file: {e}")
        else:
            print("Could not determine job ID to locate modal HTML file.")
    else:
        print("\nInfo: --modal-html-dir not provided. Skipping Easy Apply modal comparison.")


if __name__ == "__main__":
    # Example usage (you would run this from your terminal):
    # python compare_html_with_csv.py --job-url-or-id "https://www.linkedin.com/jobs/view/1234567890" \
    # --csv-file "results_20231027_120000/job_details.csv" \
    # --results-dir "results_20231027_120000" \
    # --modal-html-dir "modal_html_dumps"
    main()
