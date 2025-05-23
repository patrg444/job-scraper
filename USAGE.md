# Project Usage Guide

This guide explains how to use the different scripts in this repository to collect LinkedIn job data, dump job page HTML, and compare the collected data.

## 1. Collecting Job Details and Main Job Page HTML

The `lite_linkedin_bot/main.py` script is used to search for jobs, collect details (like title, company, description snippets), and save the main HTML content of each job page.

**Configuration:**

*   Ensure your LinkedIn credentials and other settings are correctly specified in `lite_linkedin_bot/config.yaml`.
*   To enable job detail collection and HTML saving, set the following in `config.yaml`:
    ```yaml
    collect_job_details: true
    # apply_to_jobs: false (if you only want to collect details)
    # collect_questions: false (if you only want to collect details)
    ```
*   You can specify search queries in `config.yaml` (e.g., `search_queries`) or provide a list of direct `job_urls`.

**Running the script:**

```bash
python lite_linkedin_bot/main.py
```

**Output:**

*   A results directory will be created (e.g., `results_YYYYMMDD_HHMMSS`).
*   Inside this directory, you'll find:
    *   `job_details.csv`: Contains the parsed job information. One of the columns is "HTML File Path".
    *   `job_page_html/`: This subdirectory contains the saved HTML files for each job page, named `job_<job_id>.html`. The "HTML File Path" in the CSV refers to these files (e.g., `job_page_html/job_1234567890.html`).

## 2. Dumping "Easy Apply" Modal HTML

The `playwright_linkedin_dom_dumper.py` script is used to navigate to a specific job URL, click the "Easy Apply" button, and save the HTML content of the page when the Easy Apply modal is active. This is useful for capturing the structure of the application form.

**Prerequisites:**

*   Ensure `config.yaml` (in `lite_linkedin_bot/`) has your LinkedIn login credentials.
*   You need to have Playwright installed and setup (`pip install playwright && playwright install`).

**Running the script:**

```bash
python playwright_linkedin_dom_dumper.py --job-url "YOUR_LINKEDIN_JOB_URL" --output-dir "your_chosen_output_directory"
```

*   Replace `"YOUR_LINKEDIN_JOB_URL"` with the full URL of the LinkedIn job posting.
*   `--output-dir` is optional and defaults to `modal_html_dumps`.

**Output:**

*   An HTML file named `easy_apply_modal_<job_id>.html` will be saved in the specified output directory (e.g., `modal_html_dumps/easy_apply_modal_1234567890.html`).
    *   `<job_id>` is extracted from the job URL.

## 3. Comparing CSV Data with Archived HTML

The `compare_html_with_csv.py` script allows you to compare the data stored in `job_details.csv` (from `main.py`) with the content of the archived HTML files (both main job page and Easy Apply modal).

**Purpose:**

This script is primarily for debugging and verification. It helps you:
*   Check if the selectors used by `lite_linkedin_bot` to parse job details are still accurate for the saved main job page HTML.
*   Inspect the structure of the Easy Apply modal HTML and compare its fields with what you might expect or what `lite_linkedin_bot`'s `FormHandler` might interact with.

**Running the script:**

```bash
python compare_html_with_csv.py \
    --job-url-or-id "YOUR_LINKEDIN_JOB_URL_OR_ID" \
    --csv-file "path/to/your/results_YYYYMMDD_HHMMSS/job_details.csv" \
    --results-dir "path/to/your/results_YYYYMMDD_HHMMSS" \
    --modal-html-dir "path/to/your_modal_html_dumps_directory"
```

*   Replace placeholders with the actual job URL/ID and paths to your files/directories.
*   `--modal-html-dir` is optional; if not provided, the modal comparison part will be skipped.

**Important Customization Note:**

*   **The HTML selectors within `compare_html_with_csv.py` are examples.** LinkedIn's website structure changes frequently. You will **very likely need to update these selectors** (using tools like browser developer tools to inspect elements) to match the current HTML structure of the job pages and modals you have archived. This script provides a starting framework for your own analysis.

## Purpose of Archived HTML Files

*   **`job_page_html/job_<job_id>.html`**:
    *   This is the full HTML of the main LinkedIn job posting page, saved by `lite_linkedin_bot/main.py` when `collect_job_details` is true.
    *   It's used by `compare_html_with_csv.py` to verify if the data parsed and saved into `job_details.csv` (e.g., job title, company name) matches what's actually on the page. This helps identify if parsing selectors in `linkedin_bot.py` need updates.

*   **`easy_apply_modal_<job_id>.html`** (e.g., in `modal_html_dumps/`):
    *   This is the full HTML of the job page, captured by `playwright_linkedin_dom_dumper.py` *after* the "Easy Apply" button has been clicked and the modal is presumed to be open.
    *   It's used by `compare_html_with_csv.py` to inspect the structure of the Easy Apply application form. This can help in understanding the form fields, labels, and overall layout that `lite_linkedin_bot`'s `FormHandler` would interact with if it were to fill out the application.

By comparing the CSV data with these HTML snapshots, you can debug parsing issues, understand how job information is presented, and verify the structure of application forms.
