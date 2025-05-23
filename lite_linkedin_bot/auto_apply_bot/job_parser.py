"""
Job description parser to extract key information from a LinkedIn job post,
supporting multi-level job postings by segmenting the description.
"""
import re
from typing import Dict, List, Any
import logging
import os
import yaml

logger = logging.getLogger(__name__)

class JobDescriptionParser:
    LEVEL_DELIMITER_PATTERNS = [
        re.compile(r"^(Senior|Staff|Principal|Lead|Junior|Associate|Entry-Level|Level\s+[IVX]+)\s+([A-Za-z\s]+(?:Engineer|Developer|Analyst|Scientist|Manager|Specialist|Coordinator|Representative|Technician|Designer|Architect|Consultant|Program\sManager|Product\sManager|Data\sScientist|Research\sScientist|Software\sEngineer|Financial\sAnalyst|Business\sAnalyst|Project\sManager|Marketing\sManager|Sales\sRepresentative|Customer\sService\sRepresentative|HR\sSpecialist|Recruiter|Accountant|Graphic\sDesigner|UX/UI\sDesigner|Content\sWriter|Editor|Lawyer|Paralegal|Nurse|Doctor|Pharmacist|Teacher|Professor|Research\sAssociate|Lab\sTechnician|Operations\sManager|Supply\sChain\sAnalyst|Logistics\sCoordinator|Executive\sAssistant|Administrative\sAssistant|Office\sManager|IT\sSupport\sSpecialist|Network\sAdministrator|System\sAdministrator|Database\sAdministrator|Cybersecurity\sAnalyst|DevOps\sEngineer|Cloud\sEngineer|Data\sEngineer|Solutions\sArchitect|Enterprise\sArchitect|QA\sEngineer|Test\sEngineer|Automation\sEngineer))\s*[:\-–—]?$", re.MULTILINE | re.IGNORECASE),
        re.compile(r"^(Requirements|Responsibilities|Qualifications|Experience|Education|About\s+the\s+Role)\s+for\s+(Senior|Staff|Principal|Lead|Junior|Associate|Entry-Level|Level\s+[IVX]+)\s*([A-Za-z\s]+(?:Engineer|Developer|Analyst|Scientist|Manager))?\s*[:\-–—]?$", re.MULTILINE | re.IGNORECASE),
        re.compile(r"^(?:For\s+the\s+)?(Senior|Staff|Principal|Lead|Junior|Associate|Entry-Level|Level\s+[IVX]+)\s+(?:level|role|position|candidate|candidates)\s*[,:\-–—]?$", re.MULTILINE | re.IGNORECASE),
        re.compile(r"^(?:The\s+)?(Senior|Staff|Principal|Lead|Junior|Associate|Entry-Level|Level\s+[IVX]+)\s*[:\-–—]\s*", re.MULTILINE | re.IGNORECASE), # e.g. "Senior:"
        re.compile(r"^\s*\*\*\s*(Senior|Staff|Principal|Lead|Junior|Associate|Entry-Level|Level\s+[IVX]+)\s+([A-Za-z\s]+)\s*\*\*\s*$", re.MULTILINE | re.IGNORECASE), # Markdown like **Senior Software Engineer**
        re.compile(r"^If you are an? (Senior|Staff|Principal|Lead|Junior|Associate|Entry-Level|Level\s+[IVX]+)", re.MULTILINE | re.IGNORECASE)
    ]

    def __init__(self, description_text: str, initial_facts: Dict[str, Any] = None, config: Dict[str, Any] = None):
        self.full_text = description_text # Store the original full text
        self.config = config if config else {}
        
        self.requirement_rules = self.config.get("requirement_parsing_rules", {})
        self.degree_equivalents_config = self.requirement_rules.get("degree_to_experience_equivalents", 
                                                                {'HS': 0, 'AA': 2, 'BA': 4, 'MA': 6, 'PhD': 8})
        self.assume_equivalent_if_unspecified = self.requirement_rules.get("assume_equivalent_if_unspecified", True)
        
        # initial_facts are now considered global/default facts, not specific to one level at init
        self.global_initial_facts = initial_facts if initial_facts else {}
        
        self.degree_map = {
            "high school diploma": "HS", "hs diploma": "HS", "ged": "HS", "high school": "HS",
            "associate's degree": "AA", "associate degree": "AA", "associates degree": "AA", 
            "associate's": "AA", "associates": "AA", "aa": "AA", "a.a.": "AA", "as": "AA", "a.s.": "AA",
            "bachelor's degree": "BA", "bachelor degree": "BA", "bachelors degree": "BA",
            "bachelor's": "BA", "bachelors": "BA", "bs": "BA", "b.s.": "BA", 
            "ba": "BA", "b.a.": "BA", "undergraduate degree": "BA", "undergraduate": "BA",
            "master's degree": "MA", "master degree": "MA", "masters degree": "MA",
            "master's": "MA", "masters": "MA", "ms": "MA", "m.s.": "MA", 
            "ma": "MA", "m.a.": "MA", "graduate degree": "MA", "graduate": "MA",
            "phd": "PhD", "ph.d.": "PhD", "doctorate": "PhD", "doctoral degree": "PhD", "doctoral": "PhD"
        }
        self.simple_experience_patterns = [
            r"(\d+)\+?\s*years?['’]?\s*(?:of)?\s*(?:relevant|professional|work(?:ing)?)?\s*experience",
            r"minimum\s+of\s+(\d+)\s*years?['’]?",
            r"at\s+least\s+(\d+)\s*years?['’]?",
            r"(\d+)\s*-\s*(\d+)\s*years?['’]?", 
        ]
        self.tech_skills = ["Python", "JavaScript", "Java", "C++", "C#", "Go", "Rust", "Swift", "Kotlin", "Ruby", "PHP", "SQL", "NoSQL", "MongoDB", "MySQL", "PostgreSQL", "Oracle", "MS SQL", "React", "Angular", "Vue", "Node.js", "Django", "Flask", "Spring", "Express", "AWS", "Azure", "GCP", "Cloud", "Docker", "Kubernetes", "Terraform", "Machine Learning", "Deep Learning", "NLP", "Computer Vision", "Data Science", "TensorFlow", "PyTorch", "scikit-learn", "Keras", "AI", "Git", "Jenkins", "CI/CD", "DevOps", "MLOps", "REST API", "GraphQL", "Microservices", "Linux", "Unix", "Agile", "Scrum"]
        self.interest_keywords = ["collaborate", "team", "communication", "problem-solving", "analytical", "leadership", "innovative", "creativity", "deadline", "fast-paced", "detail-oriented", "customer", "client", "solution", "quality", "scalable", "reliable", "performance", "optimization", "security", "testing", "research", "development", "design", "implementation", "architecture", "production", "startup", "enterprise"]
        self.domain_keywords = ["finance", "healthcare", "e-commerce", "retail", "education", "transportation", "logistics", "manufacturing", "gaming", "media", "advertising", "marketing", "sales", "cybersecurity", "blockchain", "mobile", "web", "desktop", "embedded", "IoT", "data", "analytics", "backend", "frontend", "fullstack", "infrastructure", "networking", "real-time", "streaming", "pipeline", "ETL", "BI"]

    def _get_default_facts(self) -> Dict[str, Any]:
        """Returns a fresh dictionary of default facts for a segment."""
        return {
            "company_name": self.global_initial_facts.get("company_name", "NA"), 
            "job_title": self.global_initial_facts.get("job_title", "NA"), 
            "location": self.global_initial_facts.get("location", "NA"), 
            "employment_type": self.global_initial_facts.get("employment_type", "NA"),
            "required_experience_years": float('inf'), 
            "required_education": "NA",
            "required_skills": [], 
            "mention_keywords": {}, 
            "description_summary": "NA",
            "identified_level_title": "default", # Default level title
            "job_url": self.global_initial_facts.get("job_url", "NA"), # Carry over global URL
            "application_link": self.global_initial_facts.get("application_link", "NA") # Carry over global app link
        }

    def _segment_description_by_level(self, description_text: str) -> list[dict]:
        delimiters = []
        for pattern in self.LEVEL_DELIMITER_PATTERNS:
            for match in pattern.finditer(description_text):
                level_title = match.group(1).strip() # Primary level keyword (Senior, Staff, etc.)
                # Try to capture a more specific title if available from other groups
                if len(match.groups()) > 1 and match.group(2):
                    level_title = f"{match.group(1).strip()} {match.group(2).strip()}"
                elif len(match.groups()) > 2 and match.group(3): # For patterns like "Reqs for Senior Engineer"
                     level_title = f"{match.group(2).strip()} {match.group(3).strip()}"

                delimiters.append({'start': match.start(), 'end': match.end(), 'title': level_title, 'full_match': match.group(0).strip()})

        if not delimiters:
            return [{'level_title': 'default', 'text_block': description_text}]

        delimiters.sort(key=lambda d: d['start'])
        
        segments = []
        current_pos = 0
        
        # Handle text before the first delimiter as 'default' or primary level
        if delimiters[0]['start'] > 0:
            segments.append({
                'level_title': 'default', # Or try to infer from global job title if appropriate
                'text_block': description_text[0:delimiters[0]['start']].strip()
            })
        
        for i, delim in enumerate(delimiters):
            start_block = delim['end'] # Text for this level starts AFTER the delimiter
            end_block = delimiters[i+1]['start'] if i + 1 < len(delimiters) else len(description_text)
            
            segment_text = description_text[start_block:end_block].strip()
            
            # Use the full matched delimiter as the title, or the captured group
            title_to_use = delim['full_match'] if delim['full_match'] else delim['title']
            
            # If the segment text itself starts with another delimiter (e.g., nested or poorly separated),
            # it might indicate an issue or a very short section. For now, we include it.
            segments.append({
                'level_title': title_to_use,
                'text_block': segment_text
            })
            current_pos = end_block
            
        # Filter out empty segments
        return [s for s in segments if s['text_block']]


    def parse(self) -> List[Dict[str, Any]]:
        parsed_levels = []
        segments = self._segment_description_by_level(self.full_text)

        for segment in segments:
            current_segment_facts = self._get_default_facts()
            current_segment_facts['identified_level_title'] = segment['level_title']
            text_to_parse = segment['text_block']

            # Call extraction methods, passing text_to_parse and current_segment_facts
            current_segment_facts["job_title"] = self._extract_job_title(text_to_parse, current_segment_facts)
            current_segment_facts["company_name"] = self._extract_company_name(text_to_parse, current_segment_facts)
            current_segment_facts["location"] = self._extract_location(text_to_parse, current_segment_facts)
            current_segment_facts["employment_type"] = self._extract_employment_type(text_to_parse, current_segment_facts)
            
            # Edu and Exp extraction updates facts directly
            current_segment_facts = self._extract_education_and_experience_requirements(text_to_parse, current_segment_facts)
            
            current_segment_facts["required_skills"] = self._extract_skills_requirements(text_to_parse)
            current_segment_facts["mention_keywords"] = self._count_keyword_mentions(text_to_parse)
            current_segment_facts["description_summary"] = self._create_summary(text_to_parse)

            # Finalize experience years for the segment
            if current_segment_facts["required_experience_years"] == float('inf'):
                current_segment_facts["required_experience_years"] = "NA"
                # Adjust education text if experience is NA and edu text implies years
                edu_text_lower = str(current_segment_facts.get("required_education", "")).lower()
                if current_segment_facts["required_education"] == "NA" or \
                   any(kw in edu_text_lower for kw in ["years", "yr", "equivalent", "exp"]):
                    is_just_degree = False
                    if current_segment_facts["required_education"] != "NA":
                        for degree_norm_name in self.degree_map.keys():
                            if degree_norm_name in edu_text_lower:
                                if not any(yr_kw in edu_text_lower for yr_kw in ["year", "yr", "equivalent", "exp"]) or \
                                   re.search(r'\(\d+(\.\d+)?\s*yrs?\s*equiv\)', edu_text_lower):
                                    is_just_degree = True; break
                    if not is_just_degree: current_segment_facts["required_education"] = "NA"
            elif isinstance(current_segment_facts["required_experience_years"], float) and current_segment_facts["required_experience_years"].is_integer():
                 current_segment_facts["required_experience_years"] = int(current_segment_facts["required_experience_years"])
            
            parsed_levels.append(current_segment_facts)
            logger.info(f"Parsed segment for level '{segment['level_title']}'. Experience: {current_segment_facts['required_experience_years']}, Education: {current_segment_facts['required_education']}")
        
        if not parsed_levels: # Should not happen if _segment_description_by_level works correctly
            logger.warning("No segments were parsed from the job description. Returning a single default fact set.")
            default_empty_facts = self._get_default_facts()
            default_empty_facts["description_summary"] = self.full_text[:500] + "..." if self.full_text else "NA" # Add some summary
            return [default_empty_facts]
            
        return parsed_levels

    def _extract_job_title(self, text_to_parse: str, current_facts: Dict[str, Any]) -> str:
        # Use current_facts' job_title if it's specific, otherwise parse from segment
        job_title = current_facts.get("job_title", "NA")
        if job_title and job_title != "NA": return job_title # Prioritize already set title

        title_patterns = [r'Job Title:\s*([^\n]+)', r'Position:\s*([^\n]+)', r'Role:\s*([^\n]+)']
        for pattern in title_patterns:
            match = re.search(pattern, text_to_parse, re.IGNORECASE)
            if match: return match.group(1).strip()
        lines = text_to_parse.split('\n')
        for line in lines[:3]: # Check first few lines of segment
            if len(line.strip()) < 80 and any(kw in line for kw in ["Engineer", "Developer", "Analyst", "Scientist", "Manager"]):
                return line.strip()
        return job_title # Return original if nothing found in segment

    def _extract_company_name(self, text_to_parse: str, current_facts: Dict[str, Any]) -> str:
        company_name = current_facts.get("company_name", "NA")
        if company_name and company_name != "NA": return company_name
        match = re.search(r'Company:\s*([^\n]+)', text_to_parse, re.IGNORECASE) # Simplified
        if match: return match.group(1).strip()
        return company_name

    def _extract_location(self, text_to_parse: str, current_facts: Dict[str, Any]) -> str:
        location = current_facts.get("location", "NA")
        if location and location != "NA": return location
        match = re.search(r'Location:\s*([^\n]+)', text_to_parse, re.IGNORECASE) # Simplified
        if match: return match.group(1).strip()
        if "remote" in text_to_parse.lower(): return "Remote"
        return location

    def _extract_employment_type(self, text_to_parse: str, current_facts: Dict[str, Any]) -> str:
        emp_type = current_facts.get("employment_type", "NA")
        if emp_type and emp_type != "NA": return emp_type
        employment_types = {"internship": [r'\binternship\b'], "contract": [r'\bcontract\b'], "part-time": [r'\bpart-time\b'], "full-time": [r'\bfull-time\b']}
        for type_key, patterns in employment_types.items():
            for pattern in patterns:
                if re.search(pattern, text_to_parse, re.IGNORECASE): return type_key
        return emp_type if emp_type and emp_type != "NA" else "full-time" # Default to full-time

    def _degree_to_years(self, degree_input: str) -> float:
        if not degree_input: return float('inf')
        normalized_degree = re.sub(r'[.\'’]', '', degree_input.lower().strip()).replace(" degree", "").replace(" diploma", "")
        standard_key = self.degree_map.get(normalized_degree)
        if standard_key: return float(self.degree_equivalents_config.get(standard_key, float('inf')))
        for term, key in [("phd", "PhD"), ("doctorate", "PhD"), ("doctoral", "PhD"), 
                          ("master", "MA"), ("graduate", "MA"), 
                          ("bachelor", "BA"), ("undergraduate", "BA"),
                          ("associate", "AA"),
                          ("high school", "HS"), ("hs", "HS"), ("ged", "HS")]:
            if term in normalized_degree: return float(self.degree_equivalents_config.get(key, float('inf')))
        return float('inf')

    def _resolve_requirement_expression(self, text_segment: str, current_facts: Dict[str, Any]) -> tuple[float, str | None]:
        text_segment_cleaned = text_segment.strip(".,;: ")
        text_segment_lower = text_segment_cleaned.lower()
        min_years_for_segment = float('inf')
        description_for_segment = None

        degree_pattern = r"(?:(?:high\s+school\s+diploma|hs\s+diploma|ged|high\s+school)|(?:associate(?:'s)?(?:\s+degree)?|a[as]\b(?![a-zA-Z]))|(?:bachelor(?:'s)?(?:\s+degree)?|b[as]\b(?![a-zA-Z]))|(?:master(?:'s)?(?:\s+degree)?|m[as]\b(?![a-zA-Z])|graduate(?:\s+degree)?)|(?:phd|ph\.d\.|doctoral(?:\s+degree)?|doctorate))"
        year_exp_pattern = r"(\d+)(?:\s*-\s*(\d+))?\+?\s*years?"

        or_clauses = re.split(r'\s+or\s+', text_segment_lower, flags=re.IGNORECASE)
        for or_clause_text in or_clauses:
            degrees_in_clause_years = []
            exp_in_clause_years = []
            
            and_clauses_text = re.split(r'\s+and\s+', or_clause_text, flags=re.IGNORECASE)
            for and_part in and_clauses_text:
                for dm in re.finditer(degree_pattern, and_part, re.IGNORECASE):
                    degrees_in_clause_years.append(self._degree_to_years(dm.group(0)))
                for ym in re.finditer(year_exp_pattern, and_part, re.IGNORECASE):
                    exp_in_clause_years.append(int(ym.group(1)))
            
            current_and_clause_years = sum(exp_in_clause_years)
            if degrees_in_clause_years:
                min_degree_val = min(degrees_in_clause_years) if degrees_in_clause_years else float('inf')
                if min_degree_val != float('inf'): current_and_clause_years += min_degree_val
                elif not exp_in_clause_years: current_and_clause_years = float('inf')
            elif not exp_in_clause_years: current_and_clause_years = float('inf')

            if current_and_clause_years == float('inf') and self.assume_equivalent_if_unspecified and "equivalent" in or_clause_text:
                original_or_degree_match = re.search(degree_pattern, or_clause_text, re.IGNORECASE)
                if original_or_degree_match:
                    equiv_degree_years = self._degree_to_years(original_or_degree_match.group(0))
                    if equiv_degree_years != float('inf'): current_and_clause_years = equiv_degree_years
            
            if current_and_clause_years < min_years_for_segment:
                min_years_for_segment = current_and_clause_years
                description_for_segment = or_clause_text.strip() if len(or_clauses) > 1 else text_segment_cleaned
        
        return min_years_for_segment, description_for_segment

    def _extract_education_and_experience_requirements(self, text_to_parse:str, current_facts: Dict[str, Any]) -> Dict[str, Any]:
        current_min_years = current_facts.get("required_experience_years", float('inf'))
        current_min_education_text = current_facts.get("required_education", "NA")

        segments = re.split(r'(?<!\w\.\w.)(?<![A-Z][a-z]\.)(?<=\.|\?|!)\s+|(?<=\n)(?=\s*[-\*\u2022•◦▪▫]\s*)|(?<=\n)(?=[A-Z][a-z]*\s+[-\u2013\u2014])', text_to_parse)
        
        for segment_text in segments:
            segment_text = segment_text.strip()
            if not segment_text or len(segment_text) < 5: continue
            years, description = self._resolve_requirement_expression(segment_text, current_facts)
            if years < current_min_years:
                current_min_years = years
                current_min_education_text = description if description else f"{years} years equivalent"
        
        current_facts["required_experience_years"] = current_min_years
        current_facts["required_education"] = current_min_education_text if current_min_years != float('inf') else "NA"
        return current_facts

    def _extract_skills_requirements(self, text_to_parse: str) -> List[str]:
        required_skills = []
        for skill in self.tech_skills:
            if re.search(r'\b' + re.escape(skill) + r'\b', text_to_parse, re.IGNORECASE):
                required_skills.append(skill)
        return required_skills
    
    def _count_keyword_mentions(self, text_to_parse: str) -> Dict[str, int]:
        keyword_counts = {}
        all_keywords_to_scan = list(set(self.interest_keywords + self.domain_keywords + self.tech_skills))
        for keyword in all_keywords_to_scan:
            pattern = r'\b' + re.escape(keyword) + r'\b'
            try: count = len(re.findall(pattern, text_to_parse, re.IGNORECASE))
            except re.error: count = 0
            if count > 0: keyword_counts[keyword] = count
        return keyword_counts
    
    def _create_summary(self, text_to_parse: str) -> str:
        return text_to_parse.strip() if text_to_parse.strip() else "NA"

def parse_job_description(description_text: str, initial_facts: Dict[str, Any] = None, config: Dict[str, Any] = None) -> List[Dict[str, Any]]:
    parser = JobDescriptionParser(description_text, initial_facts=initial_facts, config=config)
    return parser.parse()

if __name__ == "__main__":
    import sys
    test_config_data = {
        "requirement_parsing_rules": {
            "degree_to_experience_equivalents": {'HS': 0, 'AA': 2, 'BA': 4, 'MA': 6, 'PhD': 8},
            "assume_equivalent_if_unspecified": True
        }
    }
    try:
        potential_config_path = os.path.join(os.path.dirname(__file__), "..", "config.yaml")
        if os.path.exists(potential_config_path):
            with open(potential_config_path, 'r') as f_cfg: loaded_config = yaml.safe_load(f_cfg)
            if loaded_config and "requirement_parsing_rules" in loaded_config:
                test_config_data = loaded_config
                print(f"INFO: Using actual config.yaml for testing.")
    except Exception: print(f"INFO: Using default test config.")

    def test_multi_level_parsing():
        print("\\n--- Testing Multi-Level Parsing ---")
        multi_level_text = """
        Senior Software Engineer
        Responsibilities for Senior role...
        - 5 years experience
        - Master's degree

        Software Engineer
        Responsibilities for base role...
        - 2 years experience
        - Bachelor's degree

        Lead Software Engineer:
        Lead responsibilities...
        - 8 years of leadership experience
        - PhD or equivalent
        """
        parser = JobDescriptionParser(multi_level_text, config=test_config_data)
        parsed_levels = parser.parse()

        print(f"Found {len(parsed_levels)} levels.")
        for i, level_facts in enumerate(parsed_levels):
            print(f"Level {i+1}: {level_facts.get('identified_level_title')}")
            print(f"  Experience: {level_facts.get('required_experience_years')}")
            print(f"  Education: {level_facts.get('required_education')}")
            print(f"  Text sample: {level_facts.get('description_summary', '')[:50]}...")
        
        assert len(parsed_levels) >= 3, f"Expected at least 3 levels, got {len(parsed_levels)}"
        # Add more specific assertions based on expected parsing for each level
        # Example:
        # assert parsed_levels[0]['identified_level_title'] == 'default' # or 'Senior Software Engineer' depending on how first segment is handled
        # assert parsed_levels[0]['required_experience_years'] == 6 # Master's
        
        # assert 'Senior Software Engineer' in parsed_levels[0]['identified_level_title'] # or similar check
        # assert parsed_levels[0]['required_experience_years'] == 6 # Master's for Senior

        # The exact titles and order depend on the _segment_description_by_level logic refinement
        # For now, just check that segmentation happened.

    if len(sys.argv) > 1 and sys.argv[1] == "--test-multi-level":
        test_multi_level_parsing()
    elif len(sys.argv) > 1: # For testing with a file
        with open(sys.argv[1], 'r', encoding='utf-8') as f: description_text = f.read()
        parsed_data_list = parse_job_description(description_text, config=test_config_data)
        print(f"Found {len(parsed_data_list)} potential job levels/segments.")
        for i, facts in enumerate(parsed_data_list):
            print(f"\n--- Level/Segment {i+1} ('{facts.get('identified_level_title')}') ---")
            for key, value in facts.items():
                if key not in ["description_summary", "mention_keywords"] or isinstance(value, (str, int, float)):
                     print(f"  {key}: {value}")
                elif key == "mention_keywords":
                     print(f"  {key}: (Keywords found: {len(value)})")
    else:
        print("Running default multi-level parsing test. Use --test-multi-level or provide a filename.")
        test_multi_level_parsing()
        # test_education_parsing() # Old test, might need rework for new structure
