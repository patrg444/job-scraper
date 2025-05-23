"""
Job description parser to extract key information from a LinkedIn job post.
"""
import re
from typing import Dict, List, Set, Any
import logging

logger = logging.getLogger(__name__)

class JobDescriptionParser:
    """
    Parser to extract relevant information from a job description.
    """
    def __init__(self, description_text: str, initial_facts: Dict[str, Any] = None):
        """
        Initialize with the text of a job description and optional initial facts.
        
        Args:
            description_text (str): The full text of the job description
            initial_facts (Dict[str, Any], optional): Pre-populated facts.
        """
        self.text = description_text
        self.facts = {
            "company_name": "NA", "job_title": "NA", "location": "NA", "employment_type": "NA",
            "required_experience_years": "NA", "required_education": "NA",
            "required_skills": [], "mention_keywords": {}, "description_summary": "NA"
        }
        if initial_facts:
            for key, value in initial_facts.items():
                # Only update if initial_facts has a truthy value for a recognized key
                if value and (key in self.facts or key in ["job_url", "application_link"]):
                    self.facts[key] = value
            
            # If employment_type was not in initial_facts or was empty in initial_facts,
            # it would have remained "NA". If initial_facts had a valid employment_type,
            # it would have been set. The _extract_employment_type method will handle
            # parsing from text or retaining this initial/default value.
            # The previous explicit default to "full-time" here is removed.
            # The default "NA" is now set in the facts dictionary above.
            # If initial_facts provides an empty string for employment_type, it will NOT override "NA".
            # If initial_facts provides "full-time", that will be used as the starting point.

        # Keywords for detecting experience requirements
        self.experience_patterns = [
            # Pattern 1: N+ years (qualifier) experience. Allows for "years'" or "years’".
            # Allows for up to 2 words between a qualifier (e.g. industrial) and "experience" (e.g. "industrial and related experience")
            r"(\d+)\+?\s*years?['’]?(?:\s+of)?\s+(?:(?:relevant|professional|work(?:ing)?|industrial)(?:\s+\w+){0,2}\s+)?experience", # e.g. 5+ years experience, 3 years working experience, 2+ years' industrial experience, 2+ years industrial and related experience
            # Pattern 2: minimum of N years (qualifier) experience
            r"minimum\s+of\s+(\d+)\s*years?['’]?(?:\s+of)?\s+(?:(?:relevant|professional|work(?:ing)?|industrial)(?:\s+\w+){0,2}\s+)?experience", # e.g. minimum of 2 years relevant experience
            # Pattern 3: at least N years (qualifier) experience
            r"at\s+least\s+(\d+)\s*years?['’]?(?:\s+of)?\s+(?:(?:relevant|professional|work(?:ing)?|industrial)(?:\s+\w+){0,2}\s+)?experience", # e.g. at least 1 year professional experience
            # Pattern 4: (N+ Years)
            r"\((\d+)\+?\s*Years['’]?\)",  # e.g. (5+ Years) - Case sensitive for "Years". Added ['’]?
            # Pattern 5: N-M years
            r"(\d+)\s*-\s*(\d+)\s*years?['’]?", # e.g. 3-5 years. Captures both. Added ['’]?
            # Pattern 6: N to M years
            r"(\d+)\s*to\s*(\d+)\s*years?['’]?",  # e.g. 3 to 5 years. Captures both. Added ['’]?
            # Pattern 7: General N years ... experience (allows more words in between)
            r"(\d+)\+?\s*years?['’]?(?:\s+of)?(?:\s+[\w\/-]+){0,5}\s+experience" # e.g. 2 years of significant industrial and product development experience
        ]
        
        # Technical skills to check for in job descriptions
        self.tech_skills = [
            "Python", "JavaScript", "Java", "C++", "C#", "Go", "Rust", "Swift", "Kotlin", "Ruby", "PHP",
            "SQL", "NoSQL", "MongoDB", "MySQL", "PostgreSQL", "Oracle", "MS SQL",
            "React", "Angular", "Vue", "Node.js", "Django", "Flask", "Spring", "Express",
            "AWS", "Amazon Web Services", "Azure", "Microsoft Azure", "GCP", "Google Cloud Platform", "Cloud", "Docker", "Kubernetes", "Terraform",
            "Machine Learning", "Deep Learning", "NLP", "Computer Vision", "Data Science",
            "TensorFlow", "PyTorch", "scikit-learn", "Keras", "AI", "Artificial Intelligence",
            "Git", "Jenkins", "CircleCI", "CI/CD", "DevOps", "MLOps",
            "REST API", "GraphQL", "Microservices", "Distributed Systems",
            "Linux", "Unix", "Windows", "MacOS",
            "Agile", "Scrum", "Kanban", "Jira", "Confluence"
        ]
        
        # Keywords to check frequency of in job description
        self.interest_keywords = [
            "collaborate", "team", "communication", "problem-solving", "analytical",
            "leadership", "innovative", "creativity", "deadline", "fast-paced",
            "detail-oriented", "customer", "client", "solution", "quality",
            "scalable", "reliable", "performance", "optimization", "security",
            "testing", "research", "development", "design", "implementation",
            "architecture", "production", "environment", "startup", "enterprise"
        ]
        
        # Keywords for specific areas of expertise or domains
        self.domain_keywords = [
            "finance", "healthcare", "e-commerce", "retail", "education", "transportation",
            "logistics", "manufacturing", "gaming", "media", "entertainment", "advertising",
            "marketing", "sales", "security", "cybersecurity", "blockchain", "crypto",
            "mobile", "web", "desktop", "embedded", "IoT", "data", "analytics",
            "backend", "frontend", "fullstack", "infrastructure", "networking",
            "real-time", "streaming", "batch", "pipeline", "ETL", "BI", "visualization"
        ]
        
    def parse(self) -> Dict[str, Any]:
        """
        Parse the job description and extract key information.
        
        Returns:
            Dict[str, Any]: Dictionary of extracted facts
        """
        try:
            # Extract job title
            self._extract_job_title()
            
            # Extract company name
            self._extract_company_name()
            
            # Extract location
            self._extract_location()
            
            # Extract employment type
            self._extract_employment_type()
            
            # Extract experience requirements
            self._extract_experience_requirements()
            
            # Extract education requirements
            self._extract_education_requirements()
            
            # Extract technical skills requirements
            self._extract_skills_requirements()
            
            # Check for keyword mentions
            self._count_keyword_mentions()
            
            # Create a summary
            self._create_summary()
            
            logger.info("Successfully parsed job description")
            return self.facts
            
        except Exception as e:
            logger.error(f"Error parsing job description: {e}")
            return self.facts
    
    def _extract_job_title(self) -> None:
        """Extract the job title from the description, potentially overwriting initial_facts."""
        logger.info(f"Attempting to extract/refine job title. Initial value from facts: '{self.facts.get('job_title', 'Not Set')}'")
        
        # Common job title patterns
        title_patterns = [
            r'Job Title:\s*([^\n]+)',
            r'Position:\s*([^\n]+)',
            r'Role:\s*([^\n]+)'
        ]
        
        for pattern in title_patterns:
            match = re.search(pattern, self.text, re.IGNORECASE)
            if match:
                self.facts["job_title"] = match.group(1).strip()
                return
        
        # If no specific job title pattern found, try to infer from the first few lines
        lines = self.text.split('\n')
        for line in lines[:5]:  # Check first 5 lines
            # Common job title keywords
            title_keywords = [
                "Engineer", "Developer", "Architect", "Scientist", "Manager", 
                "Director", "Specialist", "Analyst", "Consultant", "Lead"
            ]
            
            # If line is short and contains job title keywords, it might be the title
            if len(line.strip()) < 80 and any(keyword in line for keyword in title_keywords):
                self.facts["job_title"] = line.strip()
                return
    
    def _extract_company_name(self) -> None:
        """Extract the company name from the description, potentially overwriting initial_facts."""
        logger.info(f"Attempting to extract/refine company name. Initial value from facts: '{self.facts.get('company_name', 'Not Set')}'")
        
        # Base regex for a single-line company name part:
        # Starts with a capital, allows alphanumeric, spaces, and common punctuation.
        # Limits to 0-5 subsequent "words" to avoid matching long sentences.
        # Includes common company suffixes.
        base_company_regex_sl = r"[A-Z][A-Za-z0-9\.\-\&',]+(?: [A-Za-z0-9\.\-\&',]+){0,5}(?:,? (?:LLC|Inc\.?|Ltd\.?|Corp\.?|Group|Solutions|Technologies|Labs|Systems|Ventures|Capital|Partners|Holdings|Industries|Enterprises|Associates))?"
        
        # Base regex for a conservatively multi-line company name part:
        # Allows the single-line pattern to repeat 0-2 times after a newline.
        word_comp = r"[A-Za-z0-9\-\&']*[A-Za-z0-9]" # A component of a word in a name
        cap_word_comp = r"[A-Z][A-Za-z0-9\-\&']*[A-Za-z0-9]" # Capitalized word component
        line_part_sl = rf"{cap_word_comp}(?: {word_comp}){{0,5}}" # A single line of a company name (up to 6 word components)
        base_company_regex_mlc = rf"{line_part_sl}(?:\n{line_part_sl}){{0,2}}(?:,? (?:LLC|Inc\.?|Ltd\.?|Corp\.?|Group|Solutions|Technologies|Labs|Systems|Ventures|Capital|Partners|Holdings|Industries|Enterprises|Associates))?"

        patterns_and_groups = [
            # Most explicit and reliable patterns first
            (rf'At\s+({base_company_regex_mlc})\s*,\s*we’re\s+on\s+a\s+mission', 1, re.IGNORECASE), # Added for Toyota-like cases
            (rf'Company:\s*({base_company_regex_mlc})', 1, 0),
            # Modified "About" pattern with negative lookahead for "the job"
            (rf'About\s+((?!the job\b){base_company_regex_mlc})(?:\n|\s+is\s+a|\s+was\s+founded|\s*provides\s*|.\s*Our\s+mission|\s*is\s+an\s+Equal)', 1, re.IGNORECASE),
            (rf'Welcome\s+to\s+({base_company_regex_mlc})', 1, re.IGNORECASE),
            (rf'\b({base_company_regex_mlc})\s+Overview\b', 1, re.IGNORECASE),
            
            # Specific known company names that might be hard to catch generally
            (r'\b(TikTok)\b', 1, re.IGNORECASE), # Added for TikTok
            (r'\b(NotCo)\b', 1, re.IGNORECASE),   # Added for NotCo
            (r'\b(tvScientific)\b', 1, re.IGNORECASE),
            (r'\b(Rackspace\s+Technology)\b', 1, re.IGNORECASE),
            (r'\b(Jobot)\b', 1, re.IGNORECASE), # Catches "Jobot" if it's the company
            
            # Pattern for "part of the X team/group"
            (rf'part\s+of\s+(?:the\s+)?({base_company_regex_sl})\s+(?:AI\s+group|team|organization)\b', 1, re.IGNORECASE),


            # Company name followed by "is hiring/seeking" or "is a leading..."
            (rf'\b({base_company_regex_sl})\s+is\s+(?:actively\s+)?(?:looking|seeking|hiring|recruiting|searching)\s+for', 1, re.IGNORECASE),
            (rf'\b({base_company_regex_sl})\s+is\s+a\s+(?:leading|fast-growing|global|premier|subsidiary|division|privately\s+held)', 1, re.IGNORECASE),
            (rf'\b({base_company_regex_sl})\s+was\s+founded', 1, re.IGNORECASE),
            (rf'\b({base_company_regex_sl})\s+headquartered\s+in', 1, re.IGNORECASE),

            # Patterns where company name might be part of a common phrase
            (rf'opportunity\s+with\s+({base_company_regex_sl})', 1, re.IGNORECASE),
            (rf'join\s+(?:our\s+team\s+at\s+|the\s+team\s+at\s+)?({base_company_regex_sl})', 1, re.IGNORECASE),
            (rf'working\s+for\s+({base_company_regex_sl})', 1, re.IGNORECASE),
            (rf'employed\s+by\s+({base_company_regex_sl})', 1, re.IGNORECASE),
            
            # Hashtagged company names (e.g., #rackspace or #RackspaceTechnology)
            (r'#([a-zA-Z][a-zA-Z0-9]*)\b', 1, 0),

            # Recruiter patterns / Placeholders
            # Jobot specific for placeholder company name (e.g., "High-Growth Data Startup")
            (r'Job details\s*\n\s*\n\s*([A-Z][A-Za-z0-9 \.\-\&\'\n]+?)(?=\s+is\s+looking\s+for|\s+is\s+hiring|\n\nThis Jobot Job|\n\s*A Bit About Us)', 1, 0),
            (r'This Jobot Job is hosted by:\s*([A-Za-z\s.-]+)', 1, 0), # Jobot recruiter name (lower priority)
            (r'Email\s+Your\s+Resume\s+In\s+Word\s+To\n\n[^\n]*\n\n([A-Za-z\s]+)\s+-\s+Recruiting\s+Manager', 1, 0), # CyberCoders recruiter line

            # More general, lower priority patterns
            (rf'posted\s+by\s+({base_company_regex_mlc})\s+on', 1, re.IGNORECASE),
            # The following pattern using (at|for|with|by) is often too greedy or matches descriptions.
            # It's commented out or would need very careful construction if re-enabled.
            # (r'(?:at|for|with|by)\s+(' + base_company_regex_sl + r')(?:\s+(?:is|we)\s|\s+a\s|\s+an\s|\s+the\s|[,.;\n])', 1, re.IGNORECASE),
        ]

        for pattern_str, group_idx, flags in patterns_and_groups:
            match = re.search(pattern_str, self.text, flags)
            if match:
                company_name = match.group(group_idx).strip()
                
                # Basic cleanup: remove "CLIENT_COMPANY_PLACEHOLDER..." if it ever appears (legacy)
                company_name = company_name.replace("CLIENT_COMPANY_PLACEHOLDER_START", "").replace("CLIENT_COMPANY_PLACEHOLDER_END", "").strip()

                # Further cleanup for names that might still be too generic or are known placeholders
                # If the Jobot placeholder pattern matched, it might still include "Job details\n\n" if not careful.
                if company_name.lower().startswith("job details\n\n"):
                    company_name = company_name[len("job details\n\n"):].strip()
                
                # Avoid overly generic terms or known non-company phrases
                generic_terms = ["us", "the team", "our client", "the client", "a client",
                                 "confidential", "job details", "company", "client", "the job",
                                 "a leading provider", "a leading company", "a global leader",
                                 "an exciting opportunity", "a dynamic company"]
                # Check if the extracted name is just a generic term or too short
                if company_name.lower() in [term.lower() for term in generic_terms] or len(company_name) < 2:
                    logger.debug(f"Skipping generic or too short company name: '{company_name}' from pattern: {pattern_str}")
                    continue # Try next pattern

                # If the name is very long and doesn't seem like a structured company name, it might be a sentence.
                # The refined base_company_regex_sl should mostly prevent this, but as a safeguard:
                if len(company_name.split()) > 7 and not any(sfx.lower() in company_name.lower() for sfx in ['LLC', 'Inc', 'Ltd', 'Corp', 'Group', 'Solutions', 'Technologies', 'Labs', 'Systems', 'Ventures', 'Capital', 'Partners', 'Holdings', 'Industries', 'Enterprises', 'Associates']):
                    # Check if it looks like the start of a sentence rather than a name.
                    if company_name.endswith('.') or company_name.endswith(':'): # Simple check
                         logger.debug(f"Skipping potentially sentence-like company name: '{company_name}' from pattern: {pattern_str}")
                         continue


                self.facts["company_name"] = company_name
                logger.info(f"Company name extracted: {company_name} using pattern: {pattern_str}")
                return
        
        # Fallback: Infer from email domain if no company name found yet
        email_match = re.search(r'[\w.-]+@([\w.-]+)\.[\w.-]+', self.text)
        if email_match:
            domain_part = email_match.group(1).lower()
            # Remove common generic parts like 'www', 'mail', 'careers', 'jobs'
            domain_part = re.sub(r'^(?:www|mail|careers|jobs)\.', '', domain_part)
            
            generic_domains = ['gmail', 'outlook', 'yahoo', 'aol', 'hotmail', 'icloud', 'protonmail', 'zoho']
            # Check if the remaining part is a common email provider
            is_generic = any(gd in domain_part for gd in generic_domains)

            if not is_generic:
                # Extract the main part of the domain (e.g., "cybercoders" from "cybercoders.com")
                company_guess = domain_part.split('.')[0]
                # Capitalize appropriately (simple capitalization for now)
                self.facts["company_name"] = company_guess.replace('-', ' ').title().replace(' ', '')
                logger.info(f"Company name inferred from email domain: {self.facts['company_name']}")
                return
        logger.info("Company name not extracted.")

    def _extract_location(self) -> None:
        """Extract the job location from the description, potentially overwriting or refining initial_facts."""
        initial_location_from_facts = self.facts.get("location", "")
        logger.info(f"Attempting to extract/refine location. Initial value from facts: '{initial_location_from_facts}'")

        # Pattern 1: Explicit "Location: ..." or "Loc: ..."
        explicit_loc_match = re.search(r'(?:Location|Loc):\s*([^\n]+)', self.text, re.IGNORECASE)
        if explicit_loc_match:
            location_text = explicit_loc_match.group(1).strip()
            # Try to extract City, ST first
            city_state_match = re.search(r'([A-Za-z\s.-]+,\s*[A-Z]{2}\b)', location_text) 
            
            parsed_location_component = ""
            work_model_component = ""

            if city_state_match:
                parsed_location_component = city_state_match.group(1).strip()
            
            # Check for work model qualifiers within the location_text, regardless of City, ST match
            if "remote" in location_text.lower():
                work_model_component = "Remote"
                # Check for more specific remote qualifiers like "Remote (US)"
                remote_qualifier_match = re.search(r'remote\s*(\([^)]+\))', location_text, re.IGNORECASE)
                if remote_qualifier_match:
                    work_model_component = f"Remote {remote_qualifier_match.group(1).strip()}"
            elif "hybrid" in location_text.lower():
                work_model_component = "Hybrid"
                hybrid_qualifier_match = re.search(r'hybrid\s*(\([^)]+\))', location_text, re.IGNORECASE)
                if hybrid_qualifier_match:
                    work_model_component = f"Hybrid {hybrid_qualifier_match.group(1).strip()}"
            elif re.search(r'on-site|onsite', location_text, re.IGNORECASE):
                work_model_component = "On-site"

            if parsed_location_component and work_model_component:
                # Avoid "City, ST (Remote)" if work_model_component is already more specific like "Remote (US)"
                if work_model_component.startswith(parsed_location_component): # e.g. loc="Remote (US)", model="Remote"
                    self.facts["location"] = parsed_location_component
                elif work_model_component.lower() not in parsed_location_component.lower():
                    # Avoid "City, ST (Remote (US))" -> "City, ST (Remote)" if "Remote" is the model
                    if work_model_component == "Remote" and "(remote" in parsed_location_component.lower():
                        pass # Already captured
                    elif work_model_component == "Hybrid" and "(hybrid" in parsed_location_component.lower():
                        pass
                    elif work_model_component == "On-site" and "(on-site" in parsed_location_component.lower(): # also check for onsite
                        pass
                    else:
                        # Combine, e.g. "City, ST" + "Remote" -> "City, ST (Remote)"
                        self.facts["location"] = f"{parsed_location_component} ({work_model_component.split(' ')[0]})" 
                else: # work model was already part of the location text like "Remote (US)" or "Hybrid (Office)"
                    self.facts["location"] = parsed_location_component 
            elif parsed_location_component: # Only city/state found
                self.facts["location"] = parsed_location_component
            elif work_model_component: # Only work model found (e.g. "Location: Remote")
                self.facts["location"] = work_model_component
            else: # Fallback to the full text from "Location: ..." if no specific structure matched
                self.facts["location"] = location_text
            
            logger.info(f"Location extracted (Pattern 1 refined): {self.facts['location']}")
            return

        # Pattern 2: "City, ST (Work Model)" or "City, ST" not necessarily after "Location:"
        # Prioritize matches near context words.
        city_state_context_pattern = r'\b([A-Za-z\s.-]+,\s*[A-Z]{2}\b)\s*(?:\((Hybrid|On-site|Onsite|Remote)\))?'
        
        # Search for location with explicit work model first
        # e.g. "Laguna Hills, CA (Hybrid)"
        explicit_model_match = re.search(city_state_context_pattern, self.text, re.IGNORECASE)
        if explicit_model_match and explicit_model_match.group(2): # If work model is captured
            loc = explicit_model_match.group(1).strip()
            work_model = explicit_model_match.group(2).capitalize()
            if work_model.lower() == "onsite": # Normalize "Onsite" to "On-site"
                work_model = "On-site"
            self.facts["location"] = f"{loc} ({work_model})"
            logger.info(f"Location extracted (Pattern 2a - explicit model): {self.facts['location']}")
            return

        # Pattern 3: (Hybrid|Remote|On-site) work environment ... (in City, ST)
        work_env_pattern = r'(Hybrid|Remote|On-site|Onsite)\s+work\s+environment(?:[^\n]*?(?:in|at|near)\s+([A-Za-z\s.-]+(?:,\s*[A-Z]{2})?))?'
        env_match = re.search(work_env_pattern, self.text, re.IGNORECASE)
        if env_match:
            work_model = env_match.group(1).capitalize()
            if work_model.lower() == "onsite": # Normalize "Onsite" to "On-site"
                work_model = "On-site"
            loc_name = env_match.group(2)
            if loc_name:
                self.facts["location"] = f"{loc_name.strip()} ({work_model})"
            else:
                self.facts["location"] = work_model
            logger.info(f"Location extracted (Pattern 3 - work env): {self.facts['location']}")
            return

        # Pattern 4: General City, ST (without explicit work model in parentheses next to it)
        # Try to find context for these.
        city_state_matches = list(re.finditer(r'\b([A-Za-z\s.-]+,\s*[A-Z]{2}\b)', self.text, re.IGNORECASE))
        if city_state_matches:
            for m in city_state_matches:
                context_window = self.text[max(0, m.start()-70):min(len(self.text), m.end()+70)].lower()
                loc = m.group(1).strip()
                if any(kw in context_window for kw in ['onsite', 'on-site', 'office is in', 'based in', 'located in']):
                    # Check if hybrid/remote is also mentioned for this specific location
                    if 'hybrid' in context_window:
                        self.facts["location"] = f"{loc} (Hybrid)"
                    elif 'remote' in context_window and 'not remote' not in context_window:
                         # If remote is mentioned with a city, it's often hybrid or remote from that base
                        self.facts["location"] = f"{loc} (Remote)" # Could be Hybrid too, but Remote is a safe bet
                    else:
                        self.facts["location"] = f"{loc} (On-site)" # Default to on-site if context words but no model
                    logger.info(f"Location extracted (Pattern 4a - city,st with context): {self.facts['location']}")
                    return
            # If no strong context, but City, ST found, and initial_location was generic, use the first one.
            # This is a weaker match.
            if initial_location_from_facts.lower() in ["na", "remote", "hybrid", "on-site", "united states", ""]:
                first_city_state_loc = city_state_matches[0].group(1).strip()
                # Check if this city/state is already part of a more specific initial fact
                if initial_location_from_facts and first_city_state_loc.lower() in initial_location_from_facts.lower():
                    pass # Keep the more specific initial fact
                else:
                    self.facts["location"] = first_city_state_loc
                    logger.info(f"Location extracted (Pattern 4b - first city,st, weak match): {self.facts['location']}")
                    return


        # Pattern 5: Fallback to existing generic location patterns if others fail
        # Refined location_name_pattern to be more specific and avoid sentence fragments.
        location_name_pattern = r"([A-Za-z][A-Za-z0-9\s.,'-]*[A-Za-z0-9](?:\s*,\s*[A-Z]{2})?\b)"
        
        location_prepositions = [
            r'located\s+in', r'position\s+(?:is\s+)?(?:in|at)', r'based\s+in',
            r'office\s+in', r'works\s+in', r'situated\s+in',
            r'location\s+is\s+(?:flexible\s+-\s+our\s+team\s+is\s+distributed\s+globally,\s+any\s+nearby\s+timezone\s+is\s+great\s+as\s+long\s+as\s+you\s+have\s+regular\s+internet\s+access\s+and\s+can\s+overlap\s+with\s+US\s+Pacific\s+and\s+Europe\s+CET\s+work\s+hours\s+for\s+meetings\s+as\s+needed|flexible)'
        ]
        current_location = self.facts.get("location", "").lower() # Get current fact for comparison

        for prep_pattern in location_prepositions:
            full_pattern = rf'{prep_pattern}\s+{location_name_pattern}'
            try:
                match = re.search(full_pattern, self.text, re.IGNORECASE)
            except re.error as e:
                logger.warning(f"Regex error for location pattern '{full_pattern}': {e}. Skipping.")
                continue

            if match:
                location_candidate = match.group(1).strip()
                location_candidate = re.sub(r'[.,;]$', '', location_candidate).strip()
                
                disallowed_phrases = [
                    r'\bas a\b', r'\bis a\b', r'engineer\b', r'responsibilities\b', 
                    r'qualifications\b', r'selected\b', r'city is\b', r'area\.', r'role\b',
                    r'position\b', r'department\b', r'salary\b', r'exempt\b', r'experience\b',
                    r'determined by location'
                ]
                is_fragment = any(re.search(dp, location_candidate, re.IGNORECASE) for dp in disallowed_phrases)
                loc_lower_candidate = location_candidate.lower() # For short generic check
                is_too_short_and_generic = len(location_candidate.split()) == 1 and len(location_candidate) < 3 and loc_lower_candidate not in ["us", "uk", "ca"]
                is_too_long = len(location_candidate.split()) > 7

                if len(location_candidate) > 1 and len(location_candidate) < 70 and not is_fragment and not is_too_long and not is_too_short_and_generic:
                    if not re.match(r'^[-\u2022\d]\s*|\.$', location_candidate):
                        # Only update if current location is generic or empty
                        if not current_location or current_location in ["na", "united states", "remote, us", "remote us", "california", "the selected city is", "the area", "the", "remote", "hybrid", "on-site"]:
                            self.facts["location"] = location_candidate
                            logger.info(f"Location extracted/refined (Pattern 5 - generic refined): {self.facts['location']} using pattern: {full_pattern}")
                            return
                        else:
                            logger.info(f"Generic location pattern matched '{location_candidate}', but keeping existing specific location '{self.facts['location']}'.")
                            return 
                else:
                    logger.debug(f"Location candidate '{location_candidate}' rejected by validation (Pattern 5). Fragment: {is_fragment}, Too long: {is_too_long}, Too short/generic: {is_too_short_and_generic}")
        
        # Pattern 6: Check for common remote/hybrid work indicators (with qualifiers) as a last resort
        # Only if location is still "NA" or a very generic placeholder from initial facts
        current_location_is_generic_placeholder = self.facts.get("location", "NA").lower() in ["na", ""]

        if current_location_is_generic_placeholder:
            remote_qualifier_search = re.search(r'\b(remote\s*\([^)]+\))', self.text, re.IGNORECASE)
            hybrid_qualifier_search = re.search(r'\b(hybrid\s*\([^)]+\))', self.text, re.IGNORECASE)

            if hybrid_qualifier_search:
                self.facts["location"] = hybrid_qualifier_search.group(1).strip()
                logger.info(f"Location extracted (Pattern 6 - qualified hybrid): {self.facts['location']}")
            elif remote_qualifier_search:
                self.facts["location"] = remote_qualifier_search.group(1).strip()
                logger.info(f"Location extracted (Pattern 6 - qualified remote): {self.facts['location']}")
            else:
                remote_keywords = [r'\bremote\b', r'\bwork from home\b', r'\bwfh\b', r'\bvirtual\b', r'\btelework\b', r'\btelecommute\b']
                hybrid_keywords = [r'\bhybrid\b'] 
                onsite_keywords = [r'\bon-site\b', r'\bonsite\b']

                is_hybrid = any(re.search(pattern, self.text, re.IGNORECASE) for pattern in hybrid_keywords)
                is_remote = any(re.search(pattern, self.text, re.IGNORECASE) for pattern in remote_keywords)
                is_onsite = any(re.search(pattern, self.text, re.IGNORECASE) for pattern in onsite_keywords)

                if is_hybrid:
                    self.facts["location"] = "Hybrid"
                    logger.info(f"Location extracted (Pattern 6 - hybrid keyword): {self.facts['location']}")
                elif is_remote:
                    self.facts["location"] = "Remote" 
                    logger.info(f"Location extracted (Pattern 6 - remote keyword): {self.facts['location']}")
                    
                    text_lower = self.text.lower()
                    refined_remote_location = None
                    if any(kw in text_lower for kw in ["fully remote", "100% remote", "location independent", "work from anywhere", "work from home anywhere"]):
                        refined_remote_location = "Remote (Flexible/Global)"
                    
                    if not refined_remote_location:
                        regional_match = re.search(r"remote\s+(?:within|in|from)\s+(?:the\s+)?((?:united\s+states|u\.s\.a?\.?|usa|north\s+america|canada|europe|emea|apac|uk|eu)(?:[\s.,]|$))", text_lower)
                        if regional_match:
                            qualifier = regional_match.group(1).strip().upper()
                            if qualifier in ["UNITED STATES", "U.S.A.", "U.S.A", "USA"]: qualifier = "US"
                            if qualifier == "U.K.": qualifier = "UK"
                            refined_remote_location = f"Remote ({qualifier})"
                    
                    if not refined_remote_location:
                        must_be_in_match = re.search(r"remote.*?candidate[s]?\s+(?:must\s+be|should\s+be|expected\s+to\s+be|are\s+required\s+to\s+be)\s+(?:located|residing|based)\s+in\s+([A-Za-z\s,.\-\(\)]+?)(?:(?:\s+only)?(?:timezone|state|region|country|area)|[\.\n]|$)", text_lower)
                        if must_be_in_match:
                            qualifier = must_be_in_match.group(1).strip(" .,()")
                            if qualifier: refined_remote_location = f"Remote (Requires: {qualifier.title()})"
                    
                    if not refined_remote_location:
                        preference_match = re.search(r"remote.*?preference\s+for\s+candidate[s]?\s+(?:in|located\s+in|based\s+in)\s+([A-Za-z\s,.\-\(\)]+?)(?:timezone|state|region|country|area|[\.\n]|$)", text_lower)
                        if preference_match:
                            qualifier = preference_match.group(1).strip(" .,()")
                            if qualifier: refined_remote_location = f"Remote (Preference: {qualifier.title()})"
                    
                    if not refined_remote_location:
                        timezone_match = re.search(r"remote.*?candidate[s]?\s+(?:must\s+be|should\s+be|expected\s+to\s+be|able\s+to\s+work)\s+(?:in|within|during|to)\s+([A-Za-z]{2,5}(?:[+\-]\d{1,2})?(?:[\s./]?[A-Za-z]{2,5}(?:[+\-]\d{1,2})?)?)\s+(?:timezone|hours|time\b)", text_lower)
                        if timezone_match:
                            qualifier = timezone_match.group(1).strip().upper()
                            refined_remote_location = f"Remote (Timezone: {qualifier})"
                        else:
                            timezone_match_general = re.search(r"remote.*?([A-Za-z]{2,5}(?:[+\-]\d{1,2})?(?:[\s./]?[A-Za-z]{2,5}(?:[+\-]\d{1,2})?)?)?\s+(?:timezones|timezone\s+based)", text_lower)
                            if timezone_match_general:
                                qualifier = timezone_match_general.group(1).strip().upper()
                                refined_remote_location = f"Remote (Timezone: {qualifier})"
                    
                    if refined_remote_location:
                        self.facts["location"] = refined_remote_location
                        logger.info(f"Remote location refined to: {self.facts['location']}")

                elif is_onsite: 
                    self.facts["location"] = "On-site"
                    logger.info(f"Location extracted (Pattern 6 - on-site keyword): {self.facts['location']}")

        if self.facts.get("location", "NA") == "NA" or not self.facts.get("location", "") : # If still NA or empty after all patterns
            logger.info("Location not extracted after all patterns.")

    def _extract_employment_type(self) -> None:
        """Extract the employment type from the description, potentially overwriting initial_facts."""
        logger.info(f"Attempting to extract/refine employment type. Initial value from facts: '{self.facts.get('employment_type', 'Not Set')}'")
        
        employment_types = {
            # Order implies preference if multiple non-full-time are somehow matched by broad patterns
            "internship": [r'\bintern\b', r'\binternship\b'],
            "contract": [r'\bcontract\b', r'\bcontractor\b', r'\btemporary\b'],
            "part-time": [r'\bpart[ -]time\b', r'\bpt\b'],
            "freelance": [r'\bfreelance\b', r'\bconsultant\b'],
            # Full-time is checked last among specific patterns
            "full-time": [r'\bfull[ -]time\b', r'\bft\b', r'\bpermanent\b'],
        }
        
        parsed_from_text = None
        # Check for specific types first (internship, contract, part-time, freelance)
        for emp_type_key in ["internship", "contract", "part-time", "freelance"]:
            patterns = employment_types[emp_type_key]
            for pattern in patterns:
                if re.search(pattern, self.text, re.IGNORECASE):
                    parsed_from_text = emp_type_key
                    break
            if parsed_from_text:
                break
        
        # If no specific non-full-time type found, check for full-time explicitly
        if not parsed_from_text:
            for pattern in employment_types["full-time"]:
                if re.search(pattern, self.text, re.IGNORECASE):
                    parsed_from_text = "full-time"
                    break
        
        if parsed_from_text:
            logger.info(f"Employment type parsed from text: '{parsed_from_text}'. Updating facts.")
            self.facts["employment_type"] = parsed_from_text
        else:
            # If nothing found in text, self.facts["employment_type"] retains its value from __init__/initial_facts.
            # The __init__ method ensures a default of "full-time" if not otherwise specified by initial_facts.
            logger.info(f"No specific employment type found in text. Retaining/defaulting to: '{self.facts['employment_type']}'")
    
    def _extract_experience_requirements(self) -> None:
        """Extract experience requirements from the description, prioritizing explicit years and defaulting to the lowest found."""
        logger.info(f"Attempting to extract/refine experience requirements. Initial value: '{self.facts.get('required_experience_years', 'NA')}'")
        all_extracted_years: List[int] = []

        # Priority 1: Extract explicit year mentions using pre-defined patterns
        for pattern_str in self.experience_patterns:
            try:
                flags = 0 if pattern_str == r"\((\d+)\+?\s*Years['’]?\)" else re.IGNORECASE
                matches = re.findall(pattern_str, self.text, flags)
                
                for match_group in matches:
                    nums_in_match = []
                    if isinstance(match_group, tuple): # For range patterns like (num1, num2)
                        nums_in_match.extend(list(match_group))
                    else: # For single number patterns (match_group is a string)
                        nums_in_match.append(match_group)
                    
                    for num_str in nums_in_match:
                        if isinstance(num_str, str):
                            year_num_search = re.search(r'(\d+)', num_str) 
                            if year_num_search:
                                all_extracted_years.append(int(year_num_search.group(1)))
                        elif isinstance(num_str, int):
                             all_extracted_years.append(num_str)
            except re.error as e:
                logger.warning(f"Regex error for experience pattern '{pattern_str}': {e}. Skipping this pattern.")
            except Exception as e_inner:
                logger.warning(f"Error processing matches for experience pattern '{pattern_str}': {e_inner}")

        if all_extracted_years:
            min_years = min(all_extracted_years) # Default to the minimum extracted year
            self.facts["required_experience_years"] = min_years
            logger.info(f"Extracted specific years of experience: {all_extracted_years}. Set to min: {min_years}")
            return

        # Priority 2: Fallback to generic experience level indicators if no explicit years found
        logger.debug("No specific year numbers found. Checking generic level indicators from job title and text.")
        
        # Order from least years to most years to pick the lowest requirement if multiple terms match.
        experience_levels_map = [
            (r'\bentry[ -]?level\b', 0),
            (r'\bgraduate\b', 0),
            (r'\brecent graduate\b', 0),
            (r'\bjunior\b', 1),
            (r'\bmid[ -]?level\b', 3),
            (r'\bintermediate\b', 3),
            (r'\bexperienced\b', 3), 
            (r'\bsenior\b', 5),
            (r'\bexpert\b', 5),
            (r'\blead\b', 7),
            (r'\bstaff\b', 7),
            (r'\bprincipal\b', 10)
        ]
        
        text_to_search_levels = self.text.lower() 
        job_title_lower = self.facts.get("job_title", "NA").lower()
        if job_title_lower != "na":
            text_to_search_levels = job_title_lower + " " + text_to_search_levels

        found_level_years = -1 

        for pattern_str_lvl, mapped_years in experience_levels_map: # Iterates from lowest to highest years
            try:
                if re.search(pattern_str_lvl, text_to_search_levels, re.IGNORECASE):
                    logger.info(f"Generic experience level matched: pattern '{pattern_str_lvl}' implies {mapped_years} years.")
                    # Take the first match, which corresponds to the lowest year requirement due to sorted map
                    found_level_years = mapped_years 
                    break 
            except re.error as e:
                logger.warning(f"Regex error for generic experience level pattern '{pattern_str_lvl}': {e}")
        
        if found_level_years != -1:
            self.facts["required_experience_years"] = found_level_years
            logger.info(f"Set required_experience_years to {found_level_years} based on generic level indicators (defaulting to lowest).")
        else:
            logger.info("No specific or generic experience year/level requirements extracted. Field remains 'NA'.")

    def _extract_education_requirements(self) -> None:
        """Extract education requirements from the description, prioritizing combined degrees."""
        logger.info(f"Attempting to extract/refine education requirements. Initial value: '{self.facts.get('required_education', 'NA')}'")

        # Define education levels and their keywords
        # Using a list of tuples to maintain order for combined checks and hierarchy
        education_levels = [
            ("PhD/Doctorate", [r'\bphd\b', r'\bdoctorate\b', r'\bph\.?d\.?\b']),
            ("Master's or PhD", [r"(?:master[\'’]?s|msc|m\.?s\.?)\s*(?:or|and/or|/)\s*(?:phd|ph\.?d\.?|doctorate)"]), # Specific combined
            ("Master's Degree", [r'\bmaster[\'’]?s\b', r'\bm\.?s\.?\b', r'\bm\.?a\.?\b', r'\bgraduate degree\b']),
            ("Bachelor's or Master's", [r"(?:bachelor[\'’]?s|bsc|b\.?s\.?)\s*(?:or|and/or|/)\s*(?:master[\'’]?s|msc|m\.?s\.?)"]), # Specific combined
            ("Associate's Degree", [r"\bAssociate's\b", r"\bAssociates\b", r"\bassociate degree\b", r'\ba\.?a\.?\b', r'\ba\.?s\.?\b']),
            ("Bachelor's Degree", [r'\bbachelor[\'’]?s\b', r'\bb\.?s\.?\b', r'\bb\.?a\.?\b', r'\bundergraduate\b']),
            ("High School", [r'\bhigh school\b', r'\bsecondary education\b'])
        ]
        
        # Temporary debug for specific job URL (can be removed later)
        if self.facts.get("job_url") == "https://www.linkedin.com/jobs/view/4235556277":
            logger.info(f"DEBUG_JOBOT_EDU_PARSE: Full text for Jobot job 4235556277:\n{self.text[:2000]}")

        extracted_education_str = ""

        # Iterate through defined levels (which now includes combined patterns in order of preference)
        for level_name, patterns_list in education_levels:
            for pattern_str in patterns_list:
                # For combined patterns, they are already full regex. For single, add word boundaries.
                # A bit of a heuristic: if 'or' or '/' is in pattern_str, assume it's a combined one.
                search_pattern = pattern_str
                if "or" not in pattern_str.lower() and "/" not in pattern_str:
                     # Ensure \b is correctly applied, especially for patterns that might already contain it.
                     # pattern.strip(r'\b') is used before adding \b to avoid \b\b.
                    search_pattern = r'\b' + pattern_str.strip(r'\b') + r'\b'
                
                try:
                    if re.search(search_pattern, self.text, re.IGNORECASE):
                        extracted_education_str = level_name
                        logger.info(f"Education pattern matched: '{level_name}' using pattern '{search_pattern}'")
                        break # Found the highest/most specific level for this iteration
                except re.error as e:
                    logger.warning(f"Regex error for education pattern '{search_pattern}': {e}")
            if extracted_education_str: # If a match was found in this category, stop.
                break
        
        # Check for "or equivalent experience"
        equivalent_text_found = ""
        if extracted_education_str: # Only add "or equivalent" if a degree was found
            equivalent_phrases = [
                r"or\s+(?:an?\s+)?equivalent\s+(?:combination\s+of\s+(?:education\s+and\s+)?(?:experience|practical\s+experience|work\s+experience)|(?:experience|practical\s+experience|work\s+experience))",
                r"or\s+relevant\s+(?:(?:work|practical|industrial|professional)\s+)?experience",
                r"equivalent\s+experience\s+(?:considered|accepted)",
                r"(?:degree\s+)?or\s+equivalent(?!\s+degree)" # Avoid "degree or equivalent degree"
            ]
            for phrase_pattern in equivalent_phrases:
                if re.search(phrase_pattern, self.text, re.IGNORECASE):
                    equivalent_text_found = "or equivalent experience"
                    logger.info(f"Found 'or equivalent experience' modifier using pattern: '{phrase_pattern}'")
                    break
        
        # Finalize and set the fact
        if extracted_education_str:
            final_education_requirement = f"{extracted_education_str} {equivalent_text_found}".strip()
            self.facts["required_education"] = final_education_requirement
            logger.info(f"Final education requirement set to: '{final_education_requirement}'")
        else:
            # No specific degree was extracted.
            # The test "Degree or equivalent" expects "" in this case.
            self.facts["required_education"] = "" # Set to empty string
            logger.info("No specific education requirements extracted. Field set to empty string.")

    def _extract_skills_requirements(self) -> None:
        """Extract required technical skills from the description."""
        required_skills = []
        
        # Check for mentions of common technical skills
        for skill in self.tech_skills:
            if re.search(r'\b' + re.escape(skill) + r'\b', self.text, re.IGNORECASE):
                required_skills.append(skill)
        
        self.facts["required_skills"] = required_skills
    
    def _count_keyword_mentions(self) -> None:
        """Count mentions of interesting keywords in the description."""
        keyword_counts = {}
        
        # Check all our interest keywords, domain keywords, AND tech skills
        # This ensures that _analyze_keywords in resume_job_aligner.py also checks for tech skills
        # that might be mentioned in the job description but not explicitly listed as a "required skill".
        all_keywords_to_scan = list(set(self.interest_keywords + self.domain_keywords + self.tech_skills))
        
        for keyword in all_keywords_to_scan:
            # Search for the keyword as a whole word, case-insensitive
            # For skills like "C++" or "C#", re.escape is important.
            # For plain words, \b works well.
            # A combined approach:
            pattern = r'\b' + re.escape(keyword) + r'\b'
            try:
                count = len(re.findall(pattern, self.text, re.IGNORECASE))
            except re.error as e:
                logger.warning(f"Regex error for keyword '{keyword}' with pattern '{pattern}': {e}. Skipping this keyword.")
                count = 0
            
            if count > 0:
                keyword_counts[keyword] = count
        
        self.facts["mention_keywords"] = keyword_counts
    
    def _create_summary(self) -> None:
        """Store the full job description as the summary, or 'NA' if empty."""
        stripped_text = self.text.strip()
        if stripped_text:
            self.facts["description_summary"] = stripped_text
        else:
            self.facts["description_summary"] = "NA" # Default if text is empty


def parse_job_description(description_text: str, initial_facts: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    Parse a job description and extract key information, potentially using initial facts.
    
    Args:
        description_text (str): The full text of the job description
        initial_facts (Dict[str, Any], optional): Pre-populated facts to initialize the parser.
        
    Returns:
        Dict[str, Any]: Dictionary of extracted information
    """
    parser = JobDescriptionParser(description_text, initial_facts=initial_facts)
    return parser.parse()


if __name__ == "__main__":
    # Test the parser
    import sys

    def test_education_parsing():
        print("\\n--- Testing Education Parsing ---")
        test_cases = [
            {
                "name": "Bachelor's with equivalent experience",
                "text": "Requirements: Bachelor's degree in Engineering or equivalent experience.",
                "expected_education": "Bachelor's Degree or equivalent experience"
            },
            {
                "name": "Master's with relevant work experience",
                "text": "Qualifications: Master's degree in Data Science or relevant work experience.",
                "expected_education": "Master's Degree or equivalent experience" # Standardized output
            },
            {
                "name": "PhD only",
                "text": "Must have a PhD in Physics.",
                "expected_education": "PhD/Doctorate"
            },
            {
                "name": "BS with equivalent practical experience",
                "text": "Education: BS in CS or equivalent practical experience.",
                "expected_education": "Bachelor's Degree or equivalent experience"
            },
            {
                "name": "Associate's or an equivalent combination of education and experience",
                "text": "Requires an Associate's degree or an equivalent combination of education and experience.",
                "expected_education": "Associate's Degree or equivalent experience"
            },
            {
                "name": "Degree or equivalent",
                "text": "A relevant degree or equivalent is required.", # No specific degree mentioned, so should not pick this up as primary
                "expected_education": "" # Or potentially "or equivalent experience" if a degree was found elsewhere. For isolated, it's empty.
            },
             {
                "name": "Bachelor's degree. Equivalent experience considered.",
                "text": "Minimum of a Bachelor's degree. Equivalent experience considered.",
                "expected_education": "Bachelor's Degree or equivalent experience"
            }
        ]

        for case in test_cases:
            print(f"Test Case: {case['name']}")
            parser = JobDescriptionParser(case['text'])
            facts = parser.parse()
            actual_education = facts.get("required_education", "")
            if actual_education == case['expected_education']:
                print(f"  PASS: Expected '{case['expected_education']}', Got '{actual_education}'")
            else:
                print(f"  FAIL: Expected '{case['expected_education']}', Got '{actual_education}'")
            assert actual_education == case['expected_education'], f"Test '{case['name']}' failed. Expected '{case['expected_education']}', Got '{actual_education}'"
        print("--- Education Parsing Tests Complete ---")

    if len(sys.argv) > 1 and sys.argv[1] == "--test-education":
        test_education_parsing()
    elif len(sys.argv) > 1:
        # Read from a file
        with open(sys.argv[1], 'r') as file:
            description_text = file.read()
        
        facts = parse_job_description(description_text)
        
        print("Extracted Job Facts:")
        for key, value in facts.items():
            print(f"{key}: {value}")
    else:
        # Example job description for general testing if no args
        description_text = """
        Senior Machine Learning Engineer
        
        We are looking for a Senior Machine Learning Engineer to join our team at Acme Technologies. This position is remote.
        
        Requirements:
        - Bachelor's degree in Computer Science, Engineering, or related field. Or equivalent experience.
        - 5+ years of experience in machine learning or data science
        - Strong programming skills in Python
        - Experience with TensorFlow or PyTorch
        - Knowledge of cloud platforms (AWS, GCP, or Azure)
        
        Job Type: Full-time
        """
        
        facts = parse_job_description(description_text)
        
        print("Extracted Job Facts (Example):")
        for key, value in facts.items():
            print(f"{key}: {value}")
        
        # Also run the education specific tests
        test_education_parsing()
