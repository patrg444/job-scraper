"""
Module to align a parsed resume with a parsed job description,
providing an alignment report and suggestions.
"""
import json
import re
from typing import Dict, List, Any, Tuple, Set
import csv
import ast # For safely evaluating string representations of dicts

# Define a hierarchy for education levels for comparison
EDUCATION_HIERARCHY = {
    "high school": 1,
    "associate's degree": 2,
    "bachelor's degree": 3,
    "master's degree": 4,
    "phd/doctorate": 5,
    # Add other common terms and map them
    "ph.d.": 5,
    "ms": 4,
    "m.s.": 4,
    "bs": 3,
    "b.s.": 3,
    "ba": 3,
    "b.a.": 3,
    "associate": 2,
    "bachelors": 3,
    "masters": 4,
    "doctorate": 5,
}

def normalize_text(text: str) -> str:
    """Helper to normalize text for comparison (lowercase, strip)."""
    return text.lower().strip() if text else ""

# Updated skill normalization maps
SKILL_NORMALIZATION_MAP = { # For direct, full-string substitutions
    "natural language processing": "nlp",
    "machine learning": "ml",
    "scikit learn": "scikit-learn",
    "tensor flow": "tensorflow",
    "py torch": "pytorch",
    # Add other direct substitutions as needed
}

PRIMARY_SKILL_IDENTIFIERS = { # Maps longer strings to a primary skill if they start with certain terms
    "aws": ["aws", "amazon web services"],
    "gcp": ["gcp", "google cloud platform"],
    "azure": ["azure", "microsoft azure"],
    # Add more primary skills and their identifying prefixes (e.g., "kubernetes": ["kubernetes", "k8s"])
}

def normalize_skill(skill: str) -> str:
    """Normalizes a single skill string with more advanced logic."""
    if not skill:
        return ""
    
    s_lower = skill.lower().strip()

    # 1. Check for exact match in SKILL_NORMALIZATION_MAP (direct substitution)
    if s_lower in SKILL_NORMALIZATION_MAP:
        return SKILL_NORMALIZATION_MAP[s_lower]

    # 2. Check if the skill starts with any of the primary skill identifiers
    for primary, identifiers in PRIMARY_SKILL_IDENTIFIERS.items():
        for identifier in identifiers:
            if s_lower.startswith(identifier):
                # Ensure it's a whole word match for the identifier if it's not the full string
                # e.g., "aws" should match "aws services" but not "awstralia"
                if len(s_lower) == len(identifier) or (len(s_lower) > len(identifier) and not s_lower[len(identifier)].isalnum()):
                    return primary # Return the primary skill key

    # 3. If no specific normalization, return the lowercased, stripped skill
    return s_lower

class ResumeJobAligner:
    """
    Compares resume data against job data to generate an alignment report.
    """
    def __init__(self, parsed_resume_data: Dict[str, Any]):
        self.resume_data = parsed_resume_data
        self.job_data: Dict[str, Any] = {}

    def _load_job_data(self, parsed_job_data: Dict[str, Any]):
        """Loads and preprocesses job data for alignment."""
        self.job_data = parsed_job_data

    def _compare_skills(self) -> Dict[str, List[str]]:
        """Compares skills from resume and job description."""
        resume_skills_raw: List[str] = self.resume_data.get("skills_profile", {}).get("all_skills_flat_list", [])
        job_skills_raw: List[str] = self.job_data.get("required_skills", [])

        # DEBUGGING: Log raw skills (Commented out)
        # print(f"DEBUG ALIGNER: Raw Resume Skills: {resume_skills_raw}")
        # print(f"DEBUG ALIGNER: Raw Job Skills: {job_skills_raw}")
        
        # Normalize skills for comparison using set comprehension
        resume_skills_set: Set[str] = {normalize_skill(skill) for skill in resume_skills_raw if skill}
        job_skills_set: Set[str] = {normalize_skill(skill) for skill in job_skills_raw if skill}

        # DEBUGGING: Log normalized skill sets (Commented out)
        # print(f"DEBUG ALIGNER: Normalized Resume Skills Set: {resume_skills_set}")
        # print(f"DEBUG ALIGNER: Normalized Job Skills Set: {job_skills_set}")

        # Retrieve original casing for matched skills for better reporting
        original_skill_forms = {}
        for s_raw in resume_skills_raw + job_skills_raw:
            if s_raw:
                norm_s = normalize_skill(s_raw)
                if norm_s not in original_skill_forms: 
                    original_skill_forms[norm_s] = s_raw

        matched_normalized_skills = list(resume_skills_set.intersection(job_skills_set))
        matched_skills = [original_skill_forms.get(s, s) for s in matched_normalized_skills]
        
        missing_from_resume_normalized = list(job_skills_set.difference(resume_skills_set))
        missing_from_resume = [original_skill_forms.get(s, s) for s in missing_from_resume_normalized]

        extra_on_resume_normalized = list(resume_skills_set.difference(job_skills_set))
        extra_on_resume = [original_skill_forms.get(s, s) for s in extra_on_resume_normalized]
        
        final_extra_on_resume = [
            skill for skill in extra_on_resume 
            if normalize_skill(skill) not in job_skills_set
        ]

        return {
            "matched_skills": sorted(list(set(matched_skills))), 
            "job_skills_missing_from_resume": sorted(list(set(missing_from_resume))),
            "resume_skills_not_in_job_requirements": sorted(list(set(final_extra_on_resume)))
        }

    def _compare_experience(self) -> Dict[str, Any]:
        """Compares experience years."""
        resume_years = self.resume_data.get("candidate_details", {}).get("self_stated_total_experience_years", 0)
        # job_required_years can be an int or the string "NA"
        job_required_years = self.job_data.get("required_experience_years", "NA") 
        
        match_status = "Not Specified in Job" # Default status

        if isinstance(job_required_years, int): # Check if it's an integer
            if job_required_years > 0:
                if resume_years >= job_required_years:
                    match_status = "Meets or Exceeds Requirement"
                else:
                    match_status = f"Below Requirement (Resume: {resume_years} years, Job: {job_required_years} years)"
            elif job_required_years == 0: # Explicitly 0 years required
                 match_status = "Job specifies 0 years experience; resume has experience." if resume_years >=0 else "Job specifies 0 years experience."
        elif job_required_years == "NA": # If it's the string "NA"
            match_status = "Job experience requirement not specified (NA)."
        # If job_required_years is something else (e.g. an unexpected string), it will keep the default "Not Specified in Job"

        return {
            "resume_stated_years": resume_years,
            "job_required_years": job_required_years, 
            "match_status": match_status
        }

    def _get_resume_max_education_level(self) -> int:
        """Determines the maximum education level from the resume based on hierarchy."""
        max_level = 0
        education_history = self.resume_data.get("education_history", [])
        for edu_item in education_history:
            level_text = normalize_text(edu_item.get("degree_level_achieved", ""))
            level_val = EDUCATION_HIERARCHY.get(level_text, 0)
            if level_val > max_level:
                max_level = level_val
        return max_level

    def _compare_education(self) -> Dict[str, Any]:
        """Compares education levels."""
        resume_max_level_val = self._get_resume_max_education_level()
        
        job_required_education_text = normalize_text(self.job_data.get("required_education", ""))
        job_required_level_val = EDUCATION_HIERARCHY.get(job_required_education_text, 0)
        
        resume_education_degrees = [
            f"{edu.get('degree_level_achieved', 'N/A')} in {edu.get('major', 'N/A')}" 
            for edu in self.resume_data.get("education_history", [])
        ]

        match_status = "Job Requirement Not Specified or Unclear"
        if job_required_level_val > 0:
            if resume_max_level_val >= job_required_level_val:
                match_status = "Meets or Exceeds Requirement"
            else:
                match_status = "Below Requirement"
        elif job_required_education_text and job_required_level_val == 0:
            match_status = "Job specifies education not in known hierarchy; manual check needed."

        return {
            "resume_education_levels_achieved": resume_education_degrees,
            "job_required_education_text": self.job_data.get("required_education", "Not Specified"),
            "match_status": match_status
        }

    def _analyze_keywords(self) -> Dict[str, Any]:
        """Analyzes job keywords against resume full text and key sections."""
        job_keywords_to_check: List[str] = list(self.job_data.get("mention_keywords", {}).keys())
        
        text_sources = [
            self.resume_data.get("full_resume_text_for_keyword_search", ""),
            self.resume_data.get("candidate_details", {}).get("summary_statement", "")
        ]
        for emp in self.resume_data.get("employment_history", []):
            text_sources.extend(emp.get("description_bullet_points", []))
        for proj in self.resume_data.get("project_history", []):
            text_sources.extend(proj.get("description_bullet_points", []))
        
        full_resume_search_text = normalize_text(" ".join(filter(None, text_sources)))

        found_keywords: List[str] = []
        missing_keywords: List[str] = []

        for keyword_raw in job_keywords_to_check:
            keyword = normalize_text(keyword_raw)
            if re.search(r'\b' + re.escape(keyword) + r'\b', full_resume_search_text):
                found_keywords.append(keyword_raw) 
            else:
                missing_keywords.append(keyword_raw)
        
        return {
            "job_mention_keywords_found_in_resume": sorted(found_keywords),
            "job_mention_keywords_missing_from_resume": sorted(missing_keywords)
        }

    def generate_alignment_report(self, parsed_job_data: Dict[str, Any]) -> Dict[str, Any]:
        """Generates a comprehensive alignment report."""
        self._load_job_data(parsed_job_data)
        
        skill_comp = self._compare_skills()
        exp_comp = self._compare_experience()
        edu_comp = self._compare_education()
        keyword_analysis = self._analyze_keywords()
        
        suggestions: List[str] = []

        if skill_comp["job_skills_missing_from_resume"]:
            suggestions.append(
                f"Consider highlighting or adding experience related to these skills mentioned in the job: {', '.join(skill_comp['job_skills_missing_from_resume'])}."
            )
        
        if "Below Requirement" in exp_comp["match_status"]:
            suggestions.append(
                f"The job asks for {exp_comp['job_required_years']} years of experience; your resume states {exp_comp['resume_stated_years']}. "
                "Ensure your resume clearly reflects all relevant experience, or be prepared to address this."
            )
            
        if "Below Requirement" in edu_comp["match_status"]:
            suggestions.append(
                f"The job requires {edu_comp['job_required_education_text']}. Your resume's highest education level might be perceived as below this. "
                "Ensure your education is clearly stated."
            )
        elif "manual check needed" in edu_comp["match_status"]:
             suggestions.append(
                f"The job specifies '{edu_comp['job_required_education_text']}' which is not in the known hierarchy. Manually verify if your education aligns."
            )

        if keyword_analysis["job_mention_keywords_missing_from_resume"]:
            suggestions.append(
                f"The job description emphasizes keywords like: {', '.join(keyword_analysis['job_mention_keywords_missing_from_resume'])}. "
                "If your experience aligns, consider incorporating these terms naturally into your resume."
            )

        if not suggestions:
            suggestions.append("Overall alignment appears good based on automated checks. Review job description manually for further tailoring.")

        report = {
            "job_url": self.job_data.get("job_url", "N/A"),
            "job_title": self.job_data.get("job_title", "N/A"),
            "company_name": self.job_data.get("company_name", "N/A"),
            "skill_comparison": skill_comp,
            "experience_comparison": exp_comp,
            "education_comparison": edu_comp,
            "keyword_analysis": keyword_analysis,
            "overall_summary_and_suggestions": suggestions
        }
        return report

def calculate_alignment_score(alignment_report: Dict[str, Any]) -> int:
    """Calculates a score based on the alignment report, with hard filters for experience and education."""
    
    # Check hard filters first
    exp_comp = alignment_report.get("experience_comparison", {})
    exp_match_status = exp_comp.get("match_status", "")
    if "Below Requirement" in exp_match_status:
        return 0 # Knock-out criteria for experience

    edu_comp = alignment_report.get("education_comparison", {})
    edu_match_status = edu_comp.get("match_status", "")
    if "Below Requirement" in edu_match_status:
        return 0 # Knock-out criteria for education

    score = 0
    # Max score can be considered 100 if not knocked out.

    # 1. Skills Score (max 70 points)
    skill_comp = alignment_report.get("skill_comparison", {})
    matched_skills_count = len(skill_comp.get("matched_skills", []))
    missing_skills_count = len(skill_comp.get("job_skills_missing_from_resume", []))
    
    skills_score = (matched_skills_count * 7) - (missing_skills_count * 4) # Adjusted weights
    skills_score = max(0, min(skills_score, 70)) 
    score += skills_score

    # 2. Experience Score (max 15 points - if not a knockout)
    if "Meets or Exceeds Requirement" in exp_match_status:
        score += 15
    elif "Not Specified in Job" in exp_match_status or \
         "Job does not specify years" in exp_match_status or \
         "Job experience requirement not specified (NA)" in exp_match_status or \
         "Job specifies 0 years experience" in exp_match_status: # Handle 0 years as neutral too
        score += 7 # Neutral score for unspecified or 0 years

    # 3. Education Score (max 15 points - if not a knockout)
    if "Meets or Exceeds Requirement" in edu_match_status:
        score += 15
    elif "Job Requirement Not Specified or Unclear" in edu_match_status:
        score += 7 # Neutral for unspecified
    elif "manual check needed" in edu_match_status: 
        score += 5 # Slightly lower for manual check needed, but not a knockout

    # Keyword score is omitted in this version to give more weight to the above.
    # Total max points: Skills (70) + Exp (15) + Edu (15) = 100.
            
    return max(0, min(score, 100))

def run_alignment_for_job(
    parsed_resume_filepath: str, 
    parsed_job_data: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Main function to load resume, align with job data, and return report.
    """
    try:
        with open(parsed_resume_filepath, 'r', encoding='utf-8') as f:
            resume_data = json.load(f)
    except FileNotFoundError:
        print(f"Error: Resume file not found at {parsed_resume_filepath}")
        return {}
    except json.JSONDecodeError:
        print(f"Error: Could not decode JSON from resume file at {parsed_resume_filepath}")
        return {}
        
    aligner = ResumeJobAligner(resume_data)
    alignment_report = aligner.generate_alignment_report(parsed_job_data)
    return alignment_report

if __name__ == "__main__":
    # --- Main execution block for processing a CSV of job details ---
    parsed_resume_filepath = "cline_parsed_resume.json"
    # Use a recent job details file as an example
    job_details_csv_filepath = "results_20250522_190435/job_details.csv" 
    
    # Ensure dummy resume exists if cline_parsed_resume.json is not found (for basic testing)
    try:
        with open(parsed_resume_filepath, 'r', encoding='utf-8') as f:
            json.load(f)
        print(f"Using existing resume: {parsed_resume_filepath}")
    except FileNotFoundError:
        print(f"Creating dummy {parsed_resume_filepath} for testing as it was not found.")
        dummy_resume_content = {
          "candidate_details": {"self_stated_total_experience_years": 3}, # Adjusted to match previous test
          "skills_profile": {"all_skills_flat_list": ["Python", "AWS (SageMaker, EC2, S3, Lambda)", "Machine Learning", "Docker", "Natural Language Processing", "TensorFlow"]},
          "education_history": [{"degree_level_achieved": "Master's Degree", "major": "Biomedical Engineering"}, {"degree_level_achieved": "Bachelor's Degree", "major": "Chemical Engineering"}],
          "full_resume_text_for_keyword_search": "Experienced in Python, AWS (SageMaker, EC2, S3, Lambda), and Machine Learning. Developed Docker containers. NLP and TensorFlow."
        }
        with open(parsed_resume_filepath, 'w', encoding='utf-8') as f:
            json.dump(dummy_resume_content, f, indent=2)
        print(f"Dummy resume created at {parsed_resume_filepath}")

    all_job_reports = []

    try:
        with open(job_details_csv_filepath, 'r', encoding='utf-8') as csvfile:
            reader = csv.DictReader(csvfile)
            job_count = 0
            for row in reader:
                job_count += 1
                print(f"\nProcessing job {job_count}: {row.get('Job Title', 'N/A')} at {row.get('Company Name', 'N/A')}")
                
                parsed_job_data = {
                    "job_url": row.get("Job URL"),
                    "job_title": row.get("Job Title"),
                    "company_name": row.get("Company Name"),
                    "required_experience_years": int(row.get("Required Experience (Years)", 0)) if row.get("Required Experience (Years)", "").isdigit() else 0,
                    "required_education": row.get("Required Education"),
                    "required_skills": [s.strip() for s in row.get("Required Skills", "").split(';') if s.strip()],
                    "description_summary": row.get("Description Summary")
                }
                
                # Safely parse "Mention Keywords"
                mention_keywords_str = row.get("Mention Keywords", "{}")
                try:
                    # Replace single quotes with double quotes for JSON compatibility if it's dict-like
                    if mention_keywords_str.startswith("{'") and mention_keywords_str.endswith("}"):
                         mention_keywords_str = mention_keywords_str.replace("'", "\"")
                    parsed_job_data["mention_keywords"] = json.loads(mention_keywords_str)
                except json.JSONDecodeError:
                    try: # Fallback for Python dict-like strings if JSON fails
                        parsed_job_data["mention_keywords"] = ast.literal_eval(mention_keywords_str)
                    except (ValueError, SyntaxError):
                        print(f"  Warning: Could not parse Mention Keywords for job: {parsed_job_data['job_title']}. Using empty dict. String was: {mention_keywords_str}")
                        parsed_job_data["mention_keywords"] = {}
                
                alignment_report = run_alignment_for_job(parsed_resume_filepath, parsed_job_data)
                
                if alignment_report:
                    score = calculate_alignment_score(alignment_report)
                    alignment_report["alignment_score"] = score
                    all_job_reports.append(alignment_report)
                else:
                    print(f"  Could not generate alignment report for job: {parsed_job_data['job_title']}")
            
            print(f"\nProcessed {job_count} jobs from {job_details_csv_filepath}")

    except FileNotFoundError:
        print(f"Error: Job details CSV file not found at {job_details_csv_filepath}")
    except Exception as e:
        print(f"An error occurred while processing the CSV: {e}")

    # Sort jobs by score (descending)
    sorted_jobs = sorted(all_job_reports, key=lambda x: x.get("alignment_score", 0), reverse=True)

    print("\n--- Top Sorted Jobs by Alignment Score ---")
    for i, report in enumerate(sorted_jobs[:5]): # Print top 5 or fewer
        print(f"\nRank {i+1}: Score {report.get('alignment_score')}")
        print(f"  Job URL: {report.get('job_url')}")
        print(f"  Job Title: {report.get('job_title')} at {report.get('company_name')}")
        skill_comp = report.get('skill_comparison', {})
        print(f"  Matched Skills: {', '.join(skill_comp.get('matched_skills',[])) if skill_comp.get('matched_skills') else 'None'}")
        print(f"  Missing Skills: {', '.join(skill_comp.get('job_skills_missing_from_resume',[])) if skill_comp.get('job_skills_missing_from_resume') else 'None'}")
        exp_comp = report.get('experience_comparison', {})
        print(f"  Experience Match: {exp_comp.get('match_status')}")
        edu_comp = report.get('education_comparison', {})
        print(f"  Education Match: {edu_comp.get('match_status')}")
        kw_analysis = report.get('keyword_analysis', {})
        print(f"  Keywords Found: {len(kw_analysis.get('job_mention_keywords_found_in_resume',[]))}")
        print(f"  Keywords Missing: {len(kw_analysis.get('job_mention_keywords_missing_from_resume',[]))}")
        
    if not sorted_jobs:
        print("No jobs were processed or scored.")
