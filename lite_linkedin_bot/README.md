# Intelligent LinkedIn Easy Apply Bot

An advanced bot to automate searching for and applying to LinkedIn Easy Apply jobs with intelligent form filling capabilities.

## Key Features

- **Intelligent Form Filling**: Uses resume data and job context to provide personalized answers
- **Resume PDF Parser**: Extracts contact details, skills, experience, education from your PDF resume
- **Job Description Analyzer**: Understands job requirements to tailor application responses
- **Advanced Question Handling**:
  - Numeric experience questions (e.g., "How many years experience with Python?")
  - Company interest questions (e.g., "Why do you want to work at Company X?")
  - Security clearance and compliance questions
  - Location and work arrangement preferences
- **LLM Integration** (Optional): Use OpenAI GPT to generate personalized responses
- **Organized Results**: Timestamped directories for application tracking
- **Question Collection Mode**: Analyze application forms without submitting

## Setup

1.  **Navigate to the project directory**:
    ```bash
    cd lite_linkedin_bot
    ```

2.  **Create a Python virtual environment** (requires Python 3.9+):
    ```bash
    python3 -m venv venv
    ```

3.  **Activate the virtual environment**:
    ```bash
    source venv/bin/activate
    ```

4.  **Install dependencies**:
    ```bash
    pip install -r requirements.txt
    ```

## Configuration

### 1. Basic Settings (config.yaml)

Edit the `config.yaml` file to add your LinkedIn credentials, job search parameters, and application behavior settings:

```yaml
# LinkedIn credentials
linkedin_email: "your_email@example.com"
linkedin_password: "your_password"
resume_path: "/path/to/your_resume.pdf"
cover_letter_path: ""  # Optional path to a cover letter PDF

# Job search parameters
search_query: "machine learning engineer california, united states easy apply remote"
date_filter: "Past week"  # Options: "Past 24 hours", "Past week", "Past month", "Past year"
pages_to_scan: 3  # Maximum number of pages to scan
max_links: 20  # Maximum number of job links to collect

# Optional: Manually specified job URLs
job_urls:
  - "https://www.linkedin.com/jobs/view/example-job-url-1/"

# LLM integration for answering complex questions
use_llm: false  # Set to true to use OpenAI API for generating answers
openai_api_key: ""  # Your OpenAI API key if use_llm is true

# Application behavior
collect_questions_only: false  # If true, will only collect form questions without submitting
add_delay_between_apps: true  # Add random delay between applications
delay_min_seconds: 60  # Minimum delay in seconds
delay_max_seconds: 180  # Maximum delay in seconds
```

### 2. Enhanced Form Answers (form_answers.yaml)

The bot now supports sophisticated form answer mapping with these sections:

```yaml
# Default values
default_dropdown: "Yes"
default_text: "N/A"

# Numeric defaults for experience-related questions
numeric_defaults:
  years_skill: 3
  deep_learning_models: 4
  model_architectures: 5
  dataset_size: 10000
  gpus: 4

# Keywords that should trigger "Yes" answers
experience_yes_keywords:
  - "python"
  - "machine learning"
  - "deep learning"
  # ...many more keywords

# Dropdown mappings (categorized by type)
dropdown_map:
  # Work Authorization Questions
  eligible to work: "Yes"
  authorized to work: "Yes"
  
  # Security Clearance
  security clearance: "Yes"
  possess security clearance: "No"
  
  # Technical Experience Confirmation
  model architectures from scratch: "Yes"
  fine tune llm: "Yes"
  deepspeed: "Yes"
  
  # And many more categories...

# Text field mappings
text_map:
  # Contact & Personal Information
  first name: "Your Name"
  phone: "123-456-7890"
  
  # Numeric Experience Questions
  years of work experience with: "3"
  how many deep learning models: "4"
  
  # Company Interest / Why Here
  why do you want to work at: "I'm excited about the opportunity to apply my machine learning expertise..."
  
  # And many more categories...

# Company-specific answers
company_specific:
  rackspace:
    employed by rackspace: "No"
    # ...more company specific answers
```

## Running the Bot

### Standard Run (Search + Apply)

This will search for jobs using the search query, then apply to them:

```bash
source venv/bin/activate
python main.py
```

### Question Collection Mode

To collect application questions without submitting applications (useful for form analysis):

```bash
python main.py --collect-questions
```

### Search Only Mode

To only search for jobs and save the URLs without applying:

```bash
python main.py --search-only
```

### Apply Only Mode

To skip the search and only apply to jobs listed in config.yaml:

```bash
python main.py --apply-only
```

### Debug Mode

To enable detailed logging for troubleshooting:

```bash
python main.py --debug
```

### Output Files

All results are saved in a timestamped directory (e.g., `results_20250510_122513/`):
- `search_results.csv`: Contains all job URLs found during search
- `applications.csv`: Records the status of each application attempt
- `application_questions.csv`: When using `--collect-questions`, records question patterns

## Disclaimer

Use this bot responsibly and in compliance with LinkedIn's terms of service. Automated tools may violate their policies.
