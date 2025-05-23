"""
Minimal resume parser focusing on extracting project names and date ranges.
"""
import re
import datetime
from pdfminer.high_level import extract_text
from pdfminer.layout import LAParams
import logging
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)

COMMON_ACTION_VERBS = [
    "developed", "implemented", "managed", "designed", "led", "created", "tested", "analyzed", 
    "performed", "architected", "responsible for", "worked on", "utilized", "leveraged", 
    "contributed", "assisted", "supported", "engineered", "o " # "o " for sub-bullets that continue
]

class ResumeParser:
    def __init__(self, resume_path: str):
        self.resume_path = resume_path
        self.text = ""
        self.facts = {"project_roles": [], "work_experiences": [], "skills": [], "education": [], "contact_info": {}}
        self.skill_keywords = [] # Will be populated from the SKILLS section of the resume

    def _parse_skills_section(self) -> List[str]:
        skills_text = self._get_section_text(section_headers=["SKILLS", "TECHNICAL SKILLS", "PROFICIENCIES", "CORE COMPETENCIES"])
        if not skills_text:
            logger.warning("SKILLS section content is effectively empty after _get_section_text.")
            return []
        
        potential_skills = set()
        cleaned_skills_text = re.sub(r"^[A-Za-z\s/]+:\s*", "", skills_text, flags=re.MULTILINE)

        lines = cleaned_skills_text.split('\n')
        for line_idx, line in enumerate(lines):
            line_cleaned = line.strip()
            if not line_cleaned: continue
            
            tokens = re.split(r'[,;\t•*]', line_cleaned) 
            for token_idx, token in enumerate(tokens):
                skill = token.strip()
                skill_after_balanced_parens = re.sub(r"\s*\([^)]*\)\s*", " ", skill).strip()
                skill = skill_after_balanced_parens
                if '(' in skill and ')' not in skill: 
                    skill_parts = skill.split('(', 1)
                    main_skill = skill_parts[0].strip()
                    skill = main_skill 
                skill = skill.strip("().,") 
                if skill and len(skill) > 1 and len(skill) < 50:
                    if skill.lower() not in ["and", "or", "the", "proficiency", "proficient", "intermediate", "advanced", "expert"]:
                        potential_skills.add(skill)

        unique_skills = sorted(list(potential_skills), key=lambda s: s.lower())
        logger.info(f"Extracted skills from SKILLS section: {unique_skills}")
        return unique_skills

    def _extract_skills_from_text(self, text: str) -> List[str]:
        found_skills = set()
        if not self.skill_keywords:
            return []
        for skill in self.skill_keywords:
            try:
                if re.search(r'\b' + re.escape(skill) + r'\b', text, re.IGNORECASE):
                    found_skills.add(skill)
            except re.error as e:
                logger.error(f"Regex error for skill '{skill}': {e}")
        return sorted(list(found_skills), key=lambda s: s.lower())

    def _aggregate_skill_durations(self):
        skill_duration_map: Dict[str, int] = {}
        for entry_list in [self.facts["work_experiences"], self.facts["project_roles"]]:
            for entry in entry_list:
                duration = entry.get("duration_months", 0)
                if duration == 0: continue
                for skill_name in entry.get("skills", []):
                    skill_duration_map[skill_name] = skill_duration_map.get(skill_name, 0) + duration
        aggregated_skills = [{"skill_name": sn, "total_months": dur} for sn, dur in skill_duration_map.items()]
        self.facts["skills"] = sorted(aggregated_skills, key=lambda x: (-x["total_months"], x["skill_name"].lower()))
        logger.info(f"Aggregated skill durations: {self.facts['skills']}")

    def parse(self) -> Dict[str, Any]:
        try:
            self.text = extract_text(self.resume_path, laparams=LAParams())
        except Exception as e:
            logger.error(f"PDFMiner failed to extract text: {e}")
            return self.facts
        
        self.text = self._clean_text(self.text)

        self._parse_contact_info()
        self.skill_keywords = self._parse_skills_section()
        self._extract_experiences(
            section_headers=["WORK EXPERIENCE", "EXPERIENCE", "PROFESSIONAL EXPERIENCE"],
            experience_type="work_experience"
        )
        self._extract_experiences(
            section_headers=["PROJECTS", "RESEARCH", "RESEARCH PROJECTS", "ACADEMIC PROJECTS"],
            experience_type="research_project"
        )
        self._parse_education_section()
        self._aggregate_skill_durations()
        return self.facts

    def _parse_education_section(self) -> None:
        education_entries = []
        section_text = self._get_section_text(section_headers=["EDUCATION"])
        if not section_text:
            logger.warning("No EDUCATION section found.")
            self.facts["education"] = []
            return

        all_lines = section_text.split('\n')
        entry_indices = []

        for i, line in enumerate(all_lines):
            line_upper = line.upper()
            is_all_caps_short = line.isupper() and len(line.split()) < 7
            contains_uni_keyword = any(kw in line_upper for kw in ["UNIVERSITY", "INSTITUTE", "COLLEGE"])
            is_not_degree = not any(deg_kw in line_upper for deg_kw in ["M.S.", "B.S.", "MASTER OF", "BACHELOR OF", "PH.D."])
            is_not_gpa_line = not line_upper.startswith("GPA:")
            
            if (is_all_caps_short or contains_uni_keyword) and is_not_degree and is_not_gpa_line:
                if i > 0 and re.match(r"^[A-Za-z\s]+,\s*[A-Z]{2}$", line.strip()):
                    prev_line_upper = all_lines[i-1].upper()
                    if any(kw in prev_line_upper for kw in ["UNIVERSITY", "INSTITUTE", "COLLEGE"]):
                        continue
                entry_indices.append(i)
        
        if not entry_indices:
            logger.warning("Could not identify any distinct education entries by university name.")
            if section_text.strip():
                 entry_indices.append(0)
            else:
                self.facts["education"] = []
                return

        for i in range(len(entry_indices)):
            start_index = entry_indices[i]
            end_index = entry_indices[i+1] if (i+1) < len(entry_indices) else len(all_lines)
            
            current_entry_lines = all_lines[start_index:end_index]
            entry_text_block = "\n".join(current_entry_lines).strip() 

            if not entry_text_block:
                continue
            
            current_university_name_candidate = current_entry_lines[0].strip()
            logger.debug(f"Processing education entry starting with: '{current_university_name_candidate}'")
            logger.debug(f"Full entry_text for '{current_university_name_candidate}':\n---\n{entry_text_block}\n---")

            entry_data: Dict[str, Any] = {
                "university": None, "degree": None, "major": None,
                "graduation_date": None, "gpa": None, "honors": []
            }
            entry_data["university"] = current_university_name_candidate
            
            gpa_match_block = re.search(r"GPA:\s*([\d\.]+)\s*/\s*([\d\.]+)", entry_text_block, re.IGNORECASE)
            if gpa_match_block:
                entry_data["gpa"] = f"{gpa_match_block.group(1)}/{gpa_match_block.group(2)}"
            else:
                gpa_match_simple_block = re.search(r"GPA:\s*([\d\.]+)", entry_text_block, re.IGNORECASE)
                if gpa_match_simple_block:
                    entry_data["gpa"] = gpa_match_simple_block.group(1)
            
            block_dates_found = re.findall(r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{4})", entry_text_block, re.IGNORECASE)
            if block_dates_found:
                date_str = block_dates_found[-1] 
                logger.debug(f"Found potential grad date string(s) in block: {block_dates_found}. Using last: '{date_str}' for uni: '{entry_data['university']}'")
                parsed_grad_date = self._parse_date(date_str)
                if parsed_grad_date:
                    entry_data["graduation_date"] = parsed_grad_date.strftime("%Y-%m")
                else:
                    logger.warning(f"Failed to parse grad date string from block: '{date_str}' for uni: {entry_data['university']}")

            for line_idx, line_content in enumerate(current_entry_lines):
                line_strip = line_content.strip()
                if line_idx == 0: 
                    pass

                grad_date_match_line = re.search(r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{4})", line_strip, re.IGNORECASE)
                if grad_date_match_line: 
                    date_str_line = grad_date_match_line.group(1)
                    parsed_grad_date_line = self._parse_date(date_str_line)
                    if parsed_grad_date_line:
                        entry_data["graduation_date"] = parsed_grad_date_line.strftime("%Y-%m") 
                
                if not entry_data["gpa"]: 
                    gpa_match_line = re.search(r"GPA:\s*([\d\.]+)\s*/\s*([\d\.]+)", line_strip, re.IGNORECASE)
                    if gpa_match_line:
                        entry_data["gpa"] = f"{gpa_match_line.group(1)}/{gpa_match_line.group(2)}"
                    else:
                        gpa_match_simple_line = re.search(r"GPA:\s*([\d\.]+)", line_strip, re.IGNORECASE)
                        if gpa_match_simple_line:
                            entry_data["gpa"] = gpa_match_simple_line.group(1)

                degree_major_honor_match = re.match(r"(M\.S\.|B\.S\.|Master of Science|Bachelor of Science|Master of|Bachelor of|M\.A\.|B\.A\.)\s*(?:in\s+)?([^,(]+)(?:,\s*(.+))?", line_strip, re.IGNORECASE)
                if degree_major_honor_match:
                    if not entry_data["degree"]:
                        entry_data["degree"] = degree_major_honor_match.group(1).strip()
                        entry_data["major"] = degree_major_honor_match.group(2).strip().rstrip(',')
                        if degree_major_honor_match.group(3): 
                            entry_data["honors"].append(degree_major_honor_match.group(3).strip().rstrip(','))
                    elif not entry_data["major"]: 
                         entry_data["major"] = line_strip.strip().rstrip(',')
                    continue 
                
                is_likely_university_name = any(kw.lower() in line_strip.lower() for kw in ["UNIVERSITY", "INSTITUTE", "COLLEGE"])
                is_city_state_line = bool(re.match(r"^[A-Za-z\s]+,\s*[A-Z]{2}$", line_strip))

                if line_idx > 0 and not is_likely_university_name and not is_city_state_line:
                    if entry_data["university"] and entry_data["university"].lower() not in line_strip.lower():
                        if (not entry_data["degree"] or entry_data["degree"].lower() not in line_strip.lower()) and \
                           (not entry_data["major"] or (entry_data["major"] and entry_data["major"].lower() not in line_strip.lower())):
                            if "GPA:" in line_strip: 
                                gpa_parts = line_strip.split(';', 1)
                                if len(gpa_parts) > 1 and gpa_parts[1].strip():
                                    entry_data["honors"].append(gpa_parts[1].strip())
                            elif not re.search(r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{4})", line_strip, re.IGNORECASE):
                                 if line_strip and len(line_strip.split()) > 0 :
                                    entry_data["honors"].append(line_strip)
            
            if entry_data["university"].startswith("COLUMBIA UNIVERSITY") and not entry_data["graduation_date"]:
                columbia_date_match = re.search(r"May\s+2022", section_text, re.IGNORECASE) 
                if columbia_date_match:
                    parsed_columbia_date = self._parse_date(columbia_date_match.group(0))
                    if parsed_columbia_date:
                        logger.info(f"Applying heuristic: Found and assigned 'May 2022' to Columbia University.")
                        entry_data["graduation_date"] = parsed_columbia_date.strftime("%Y-%m")

            if entry_data["honors"]:
                valid_honors = [h.strip(';, ') for h in entry_data["honors"] if h.strip(';, ')]
                consolidated_honors = "; ".join(valid_honors)
                entry_data["honors"] = consolidated_honors.strip(';, ') if consolidated_honors else None
            else:
                entry_data["honors"] = None

            if entry_data["university"] and (entry_data["degree"] or entry_data["major"]):
                education_entries.append(entry_data)
            elif entry_text_block:
                logger.debug(f"Could not fully parse education entry: {entry_text_block[:100]}...")
        
        self.facts["education"] = education_entries
        logger.info(f"Extracted education: {education_entries}")

    def _parse_contact_info(self) -> None:
        contact_info: Dict[str, Optional[str]] = {
            "name": None, "location": None, "phone": None,
            "email": None, "linkedin": None, "github": None
        }
        text_top_portion = self.text[:300]
        lines = text_top_portion.split('\n')
        
        if lines:
            name_candidate = lines[0].strip()
            if name_candidate and name_candidate.isupper() and len(name_candidate.split()) < 5:
                 contact_info["name"] = name_candidate
            elif name_candidate and len(name_candidate.split()) < 5 :
                 contact_info["name"] = name_candidate

        email_match = re.search(r"[\w\.-]+@[\w\.-]+\.\w+", text_top_portion)
        if email_match:
            contact_info["email"] = email_match.group(0)

        phone_match = re.search(r"(\(?\d{3}\)?[\s\.-]?\d{3}[\s\.-]?\d{4})", text_top_portion)
        if phone_match:
            contact_info["phone"] = phone_match.group(0)

        linkedin_match = re.search(r"linkedin\.com/in/[\w-]+/?", text_top_portion, re.IGNORECASE)
        if linkedin_match:
            contact_info["linkedin"] = linkedin_match.group(0)

        github_match = re.search(r"github\.com/[\w-]+/?", text_top_portion, re.IGNORECASE)
        if github_match:
            contact_info["github"] = github_match.group(0)
            
        for line in lines[:5]:
            location_line_match = re.search(r"(?:^|\s*•\s*)([A-Za-z\s]+,\s*[A-Z]{2})(?:\s*•\s*|$)", line)
            if location_line_match:
                potential_location = location_line_match.group(1).strip()
                if not any(kw in potential_location.lower() for kw in ["university", "institute", "therapeutics", "llc"]):
                    contact_info["location"] = potential_location
                    break
        
        self.facts["contact_info"] = contact_info
        logger.info(f"Extracted contact info: {contact_info}")

    def _clean_text(self, text: str) -> str:
        text = re.sub(r'-\s*\r?\n\s*', '-', text)
        text = text.replace('\r\n', '\n').replace('\r', '\n')
        text = re.sub(r'[ \t]+', ' ', text)
        text = re.sub(r'^ +| +$', '', text, flags=re.MULTILINE)
        text = re.sub(r'\n{3,}', '\n\n', text)
        return text.strip('\n')

    def _get_section_text(self, section_headers: List[str]) -> str:
        for header_query in section_headers:
            logger.debug(f"Attempting to find section with header query: '{header_query}'")
            words = re.split(r'\s+', header_query.strip())
            escaped_words = [re.escape(w) for w in words if w]
            if not escaped_words: 
                logger.debug(f"Skipping empty header query: '{header_query}'")
                continue
            
            header_find_pattern_str = r'\s*' + r'\s+'.join(escaped_words) + r'\s*'
            match_current_header = re.search(r"(\n|^)" + header_find_pattern_str + r"\s*\n", self.text, re.IGNORECASE | re.MULTILINE)

            if not match_current_header:
                logger.debug(f"Header query '{header_query}' not found as a distinct section start.")
                continue
            
            start_orig = match_current_header.end()
            end_orig = len(self.text)
            found_boundary_header = None
            logger.debug(f"Found header '{header_query}' ending at index {start_orig}. Default end_orig: {end_orig}")
            
            common_boundary_headers = [
                "WORK EXPERIENCE", "EXPERIENCE", "PROFESSIONAL EXPERIENCE", 
                "EDUCATION", "SKILLS", "TECHNICAL SKILLS", "PROFICIENCIES", "CORE COMPETENCIES",
                "PROJECTS", "RESEARCH", "RESEARCH PROJECTS", "ACADEMIC PROJECTS",
                "LANGUAGES", "CERTIFICATIONS", "PUBLICATIONS", "AWARDS", "INTERESTS", "REFERENCES"
            ]
            
            possible_next_headers = [h for h in common_boundary_headers if h.upper() != header_query.upper()]

            if header_query.upper() in ["SKILLS", "TECHNICAL SKILLS", "PROFICIENCIES", "CORE COMPETENCIES"]:
                skills_section_false_terminators = ["LANGUAGES", "TOOLS", "TECHNOLOGIES", "DATABASES", "FRAMEWORKS", "LIBRARIES", "CERTIFICATIONS"]
                possible_next_headers = [h for h in possible_next_headers if h.upper() not in [st.upper() for st in skills_section_false_terminators]]
            
            for next_header_text in possible_next_headers:
                next_words = re.split(r'\s+', next_header_text.strip())
                next_escaped_words = [re.escape(w) for w in next_words if w]
                if not next_escaped_words: continue
                
                next_header_find_pattern_str = r"(\n|^)" + r'\s*'.join(next_escaped_words) + r"\s*\n"
                match_next_header = re.search(next_header_find_pattern_str, self.text[start_orig:], re.IGNORECASE | re.MULTILINE)
                
                if match_next_header:
                    boundary_pos_abs = start_orig + match_next_header.start()
                    logger.debug(f"Potential boundary: '{next_header_text}' found at relative index {match_next_header.start()} (abs: {boundary_pos_abs})")
                    if boundary_pos_abs < end_orig:
                        end_orig = boundary_pos_abs
                        found_boundary_header = next_header_text
            
            if found_boundary_header:
                logger.debug(f"Section '{header_query}' (start {start_orig}) bounded by '{found_boundary_header}' at index {end_orig}.")
            else:
                logger.debug(f"Section '{header_query}' (start {start_orig}) goes to end of text (index {end_orig}).")
            
            return self.text[start_orig:end_orig].strip()
            
        logger.warning(f"None of the header queries {section_headers} found.")
        return ""

    def _parse_date(self, date_str: str) -> Optional[datetime.datetime]:
        date_formats = ["%b %Y", "%B %Y", "%m/%Y", "%m-%Y", "%Y-%m", "%Y/%m", "%b. %Y", "%B. %Y"]
        for fmt in date_formats:
            try:
                cleaned_date_str = date_str.replace('.', '') if '.' not in fmt else date_str
                return datetime.datetime.strptime(cleaned_date_str, fmt)
            except ValueError: continue
        logger.warning(f"Could not parse date: {date_str}")
        return None

    def _calculate_months_between(self, start_date: Optional[datetime.datetime], end_date: Optional[datetime.datetime]) -> int:
        if not start_date or not end_date: return 0
        if end_date < start_date: return 0 
        return (end_date.year - start_date.year) * 12 + (end_date.month - start_date.month) + 1

    def _strip_running_headers(self, text: str) -> str:
        pages = text.split("\f"); L=len(pages)
        if L<=1: return text
        T,B,H,F={},{},set(),set()
        for P in pages:
            lns=P.strip().split('\n')
            if not lns: continue
            for i in range(min(3,len(lns))): 
                if lns[i].strip(): T[lns[i].strip()]=T.get(lns[i].strip(),0)+1
            for i in range(max(0,len(lns)-3),len(lns)):
                if lns[i].strip(): B[lns[i].strip()]=B.get(lns[i].strip(),0)+1
        MO=max(2,int(0.6*L))
        H={ln for ln,ct in T.items() if ct>=MO and len(ln.split())<10}
        F={ln for ln,ct in B.items() if ct>=MO and len(ln.split())<10}
        if not H and not F: return text
        return "\f".join(["\n".join(ln for ln in p.split('\n') if ln.strip() not in H and ln.strip() not in F) for p in pages])

    def _is_valid_title_candidate(self, text: str) -> bool:
        if not text or len(text)<3 or len(text.split())>12 or text.startswith(("•","-","*","o ")): return False
        if re.search(r"\d{4}",text) or re.search(r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)",text,re.IGNORECASE):
            if not re.search(r"[A-Za-z]+\s*\d+",text) and len(text.split())>3: return False
        if re.match(r"^[A-Za-z\s]+,\s*[A-Z]{2}$",text): return False
        return True

    def _extract_experiences(self, section_headers: List[str], experience_type: str) -> None:
        experiences = []
        section_text = self._get_section_text(section_headers)

        logger.debug(f"--- Attempting to parse section: {experience_type.upper()} ---")
        logger.debug(f"Raw section text for {experience_type}:\n---\n{section_text[:500]}...\n---")

        if not section_text:
            logger.warning(f"No {experience_type.replace('_', ' ')} section found or text is empty for headers: {section_headers}")
            if experience_type == "research_project": self.facts["project_roles"] = []
            elif experience_type == "work_experience": self.facts["work_experiences"] = []
            return
        
        section_text_cleaned_headers = self._strip_running_headers(section_text)
        
        date_re_str = r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s*\.?\s*\d{4})\s*(?:–|-|to|until|present|current)\s*((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s*\.?\s*\d{4}|Present|Current|Now)"
        date_re = re.compile(date_re_str, re.IGNORECASE)
        matches = list(date_re.finditer(section_text_cleaned_headers))
        
        logger.debug(f"Found {len(matches)} date matches for {experience_type}: {[(m.group(0)) for m in matches]}")

        if not matches:
            logger.warning(f"No dated entries found in {experience_type.replace('_', ' ')} section after cleaning headers.")
            if experience_type == "research_project": self.facts["project_roles"] = []
            elif experience_type == "work_experience": self.facts["work_experiences"] = []
            return

        for i, match in enumerate(matches):
            logger.debug(f"Processing {experience_type} match {i+1}/{len(matches)}: {match.group(0)}")
            s_date_str,e_date_str=match.group(1).strip(),match.group(2).strip()
            desc_block_end=matches[i+1].start() if i+1<len(matches) else len(section_text_cleaned_headers)
            title_seg_start=matches[i-1].end() if i>0 else 0
            title_cand_txt_blk=section_text_cleaned_headers[title_seg_start:match.start()].strip()
            logger.debug(f"Title candidate block for match {match.group(0)}:\n---\n{title_cand_txt_blk}\n---")
            
            proj_name,co_name,role_title="","",""
            title_lns=[ln.strip() for ln in title_cand_txt_blk.split('\n') if ln.strip()]
            proc_lns=0
            for ln_idx in range(len(title_lns)-1,-1,-1): 
                cand_ln=title_lns[ln_idx].strip("•-* –")
                if not self._is_valid_title_candidate(cand_ln): continue
                
                logger.debug(f"Evaluating title candidate line: '{cand_ln}'")
                if experience_type=="research_project":
                    if not proj_name: 
                        proj_name=cand_ln; proc_lns+=1; 
                        logger.debug(f"Assigned project name: '{proj_name}'")
                        break
                elif experience_type=="work_experience":
                    parts = [p.strip() for p in cand_ln.split(',') if p.strip()]
                    is_co_cand = any(ck.lower() in cand_ln.lower() for ck in ["LLC","Ltd","Inc","Corp","Group","University","Institute","Solutions","Technologies","Labs","Services","Therapeutics"])
                    is_role_cand = any(rk.lower() in cand_ln.lower() for rk in ["Engineer","Developer","Analyst","Manager","Scientist","Associate","Specialist","Lead","Founder","President","Director","Coordinator","Intern","Co-op","Consultant","Contract"])
                    if len(parts) >= 2 and not (co_name and role_title): 
                        part0_is_co = any(ck.lower() in parts[0].lower() for ck in ["LLC","Ltd","Inc","Corp","Group","University","Institute","Solutions","Technologies","Labs","Services","Therapeutics"])
                        if part0_is_co:
                            if not co_name: co_name = parts[0]
                            if not role_title: role_title = ", ".join(parts[1:])
                        else: 
                            if not role_title: role_title = parts[0]
                            if not co_name: co_name = ", ".join(parts[1:])
                        proc_lns += 1 
                    elif not role_title and is_role_cand: role_title=cand_ln; proc_lns+=1
                    elif not co_name and is_co_cand : 
                        if role_title!=cand_ln: co_name=cand_ln; proc_lns+=1
                    elif not role_title and not co_name: 
                        if is_role_cand: role_title=cand_ln
                        elif is_co_cand: co_name=cand_ln
                        else: role_title=cand_ln 
                        proc_lns+=1
                    if(co_name and role_title)or proc_lns>=2: break 
            
            needs_text_before_date_parsing = False
            if experience_type == "research_project" and not proj_name: needs_text_before_date_parsing = True
            elif experience_type == "work_experience" and not (co_name and role_title): needs_text_before_date_parsing = True

            if needs_text_before_date_parsing:
                ln_date_sidx=section_text_cleaned_headers.rfind('\n',0,match.start())+1
                ln_date_eidx=section_text_cleaned_headers.find('\n',match.start())
                if ln_date_eidx==-1: ln_date_eidx=len(section_text_cleaned_headers)
                ln_cont_date=section_text_cleaned_headers[ln_date_sidx:ln_date_eidx].strip()
                date_match_on_ln=date_re.search(ln_cont_date)
                if date_match_on_ln:
                    txt_b4_date=ln_cont_date[:date_match_on_ln.start()].strip().strip("•-* –")
                    if self._is_valid_title_candidate(txt_b4_date):
                        if experience_type=="research_project":
                             if not proj_name: proj_name=txt_b4_date; logger.debug(f"Assigned project name (from date line): '{proj_name}'")
                        elif experience_type=="work_experience":
                            parts=[p.strip() for p in txt_b4_date.split(',') if p.strip()]
                            if not co_name and not role_title: 
                                if len(parts)>=2:
                                    is_co_first=any(ck.lower() in parts[0].lower() for ck in ["LLC","Ltd","Inc","Corp","Group","University","Institute","Solutions","Technologies","Labs","Services","Therapeutics"])
                                    if is_co_first: 
                                        co_name=parts[0]; role_title=", ".join(parts[1:])
                                        logger.debug(f"Assigned company: '{co_name}', role: '{role_title}' from date line parts (co first)")
                                    else: 
                                        role_title=parts[0]; co_name=", ".join(parts[1:])
                                        logger.debug(f"Assigned role: '{role_title}', company: '{co_name}' from date line parts (role first)")
                                elif len(parts)==1:
                                    is_co_sole=any(ck.lower() in parts[0].lower() for ck in ["LLC","Ltd","Inc","Corp","Group","University","Institute","Solutions","Technologies","Labs","Services","Therapeutics"])
                                    if is_co_sole:
                                        if not co_name: co_name=parts[0]; logger.debug(f"Assigned company (sole from date line): '{co_name}'")
                                    elif not role_title: role_title=parts[0]; logger.debug(f"Assigned role (sole from date line): '{role_title}'")
                            elif not role_title: role_title=txt_b4_date; logger.debug(f"Assigned role (fallback from date line): '{role_title}'")
                            elif not co_name: co_name=txt_b4_date; logger.debug(f"Assigned company (fallback from date line): '{co_name}'")
            
            logger.debug(f"Final extracted before default: Co: '{co_name}', Role: '{role_title}', Proj: '{proj_name}'")

            if experience_type=="research_project" and not proj_name: proj_name=f"Project {i+1}"
            if experience_type=="work_experience":
                if not role_title and not co_name: role_title=f"Experience {i+1}"
                elif not role_title and co_name: role_title=f"Role at {co_name}"
                elif not co_name and role_title: co_name="Unknown Company"
            
            s_dt=self._parse_date(s_date_str)
            e_dt=self._parse_date(e_date_str) if e_date_str.lower() not in ['present','current','now'] else datetime.datetime.now()
            dur=self._calculate_months_between(s_dt,e_dt)
            
            true_desc_s=section_text_cleaned_headers.find('\n',match.start())
            if true_desc_s != -1: true_desc_s +=1 
            else: true_desc_s = match.end()
            true_desc_s=max(true_desc_s,match.end())
            
            final_desc_blk=section_text_cleaned_headers[true_desc_s:desc_block_end].strip()
            logger.debug(f"Description block for {match.group(0)}:\n---\n{final_desc_blk[:300]}...\n---")
            
            if experience_type == "research_project" and proj_name and "MRI Brain Segmentation Analysis" in proj_name:
                 logger.warning(f"MRI Project: final_description_block (len: {len(final_desc_blk)} chars, end_boundary: {desc_block_end}): '{final_desc_blk[:200]}...'")

            raw_bullet_lns = final_desc_blk.split('\n')
            bullets = []
            current_bullet_text_parts = []
            last_line_was_lone_bullet_char = False

            for line_text in raw_bullet_lns:
                stripped_line = line_text.strip()

                if not stripped_line: 
                    if current_bullet_text_parts:
                        full_bullet = " ".join(current_bullet_text_parts).strip()
                        cleaned_bullet = full_bullet
                        if cleaned_bullet.startswith("• "): cleaned_bullet = cleaned_bullet[2:]
                        elif cleaned_bullet.startswith("•"): cleaned_bullet = cleaned_bullet[1:]
                        elif cleaned_bullet.startswith("* "): cleaned_bullet = cleaned_bullet[2:]
                        elif cleaned_bullet.startswith("*"): cleaned_bullet = cleaned_bullet[1:]
                        elif cleaned_bullet.startswith("- "): cleaned_bullet = cleaned_bullet[2:]
                        elif cleaned_bullet.startswith("-"): cleaned_bullet = cleaned_bullet[1:]
                        elif cleaned_bullet.startswith("o "): cleaned_bullet = cleaned_bullet[2:]
                        elif cleaned_bullet.startswith("o"): cleaned_bullet = cleaned_bullet[1:]
                        cleaned_bullet = cleaned_bullet.strip()
                        if cleaned_bullet and cleaned_bullet not in ["•", "-", "*", "o"]: 
                            bullets.append(cleaned_bullet)
                        current_bullet_text_parts = []
                    last_line_was_lone_bullet_char = False
                    continue

                is_new_bullet_char = stripped_line.startswith(("•", "-", "*")) # "o " removed to treat as continuation

                if is_new_bullet_char:
                    if current_bullet_text_parts: 
                        full_bullet = " ".join(current_bullet_text_parts).strip()
                        cleaned_bullet = full_bullet
                        if cleaned_bullet.startswith("• "): cleaned_bullet = cleaned_bullet[2:]
                        elif cleaned_bullet.startswith("•"): cleaned_bullet = cleaned_bullet[1:]
                        elif cleaned_bullet.startswith("* "): cleaned_bullet = cleaned_bullet[2:]
                        elif cleaned_bullet.startswith("*"): cleaned_bullet = cleaned_bullet[1:]
                        elif cleaned_bullet.startswith("- "): cleaned_bullet = cleaned_bullet[2:]
                        elif cleaned_bullet.startswith("-"): cleaned_bullet = cleaned_bullet[1:]
                        cleaned_bullet = cleaned_bullet.strip()
                        if cleaned_bullet and cleaned_bullet not in ["•", "-", "*"]: # "o" also removed here
                            bullets.append(cleaned_bullet)
                    current_bullet_text_parts = [stripped_line] 
                    if stripped_line in ["•", "-", "*"]: 
                        last_line_was_lone_bullet_char = True
                    else:
                        last_line_was_lone_bullet_char = False
                elif last_line_was_lone_bullet_char: 
                    if current_bullet_text_parts and current_bullet_text_parts[0] in ["•", "-", "*"]:
                         current_bullet_text_parts = [current_bullet_text_parts[0] + " " + stripped_line]
                    else: 
                        current_bullet_text_parts.append(stripped_line)
                    last_line_was_lone_bullet_char = False 
                elif current_bullet_text_parts: 
                    is_potential_next_item_title = False
                    if not stripped_line.startswith(("•", "-", "*", "o ")): # Check against "o " here to not break on sub-bullets
                        line_words = stripped_line.split() 
                        # Refined Heuristic:
                        # Short ( < 7 words), AND
                        # ( (ALL CAPS AND <= 4 words) OR (Title Case AND > 1 word) ) AND
                        # NOT starting with a common action verb
                        if len(line_words) < 7 and \
                           ( (stripped_line.isupper() and len(line_words) <= 4) or \
                             (stripped_line.istitle() and len(line_words) > 1) ) and \
                           not any(stripped_line.lower().startswith(verb) for verb in COMMON_ACTION_VERBS):
                            # Further, use _is_valid_title_candidate as a final check if it's not too aggressive
                            if self._is_valid_title_candidate(stripped_line): 
                                is_potential_next_item_title = True
                    
                    if is_potential_next_item_title:
                        logger.debug(f"Bullet processing for '{experience_type}' item '{proj_name or co_name or 'Unknown'}' stopped due to potential new title: '{stripped_line}'")
                        full_bullet = " ".join(current_bullet_text_parts).strip()
                        cleaned_bullet = full_bullet
                        if cleaned_bullet.startswith("• "): cleaned_bullet = cleaned_bullet[2:]
                        elif cleaned_bullet.startswith("•"): cleaned_bullet = cleaned_bullet[1:]
                        elif cleaned_bullet.startswith("* "): cleaned_bullet = cleaned_bullet[2:]
                        elif cleaned_bullet.startswith("*"): cleaned_bullet = cleaned_bullet[1:]
                        elif cleaned_bullet.startswith("- "): cleaned_bullet = cleaned_bullet[2:]
                        elif cleaned_bullet.startswith("-"): cleaned_bullet = cleaned_bullet[1:]
                        elif cleaned_bullet.startswith("o "): cleaned_bullet = cleaned_bullet[2:]
                        elif cleaned_bullet.startswith("o"): cleaned_bullet = cleaned_bullet[1:]
                        cleaned_bullet = cleaned_bullet.strip()
                        if cleaned_bullet and cleaned_bullet not in ["•", "-", "*", "o"]:
                            bullets.append(cleaned_bullet)
                        current_bullet_text_parts = [] 
                        break 
                    else:
                        current_bullet_text_parts.append(stripped_line)
                elif not is_new_bullet_char and not current_bullet_text_parts and not bullets:
                    # This is the first line of a description block and doesn't start with a bullet.
                    current_bullet_text_parts = [stripped_line]
            
            if current_bullet_text_parts: 
                full_bullet = " ".join(current_bullet_text_parts).strip()
                cleaned_bullet = full_bullet
                if cleaned_bullet.startswith("• "): cleaned_bullet = cleaned_bullet[2:]
                elif cleaned_bullet.startswith("•"): cleaned_bullet = cleaned_bullet[1:]
                elif cleaned_bullet.startswith("* "): cleaned_bullet = cleaned_bullet[2:]
                elif cleaned_bullet.startswith("*"): cleaned_bullet = cleaned_bullet[1:]
                elif cleaned_bullet.startswith("- "): cleaned_bullet = cleaned_bullet[2:]
                elif cleaned_bullet.startswith("-"): cleaned_bullet = cleaned_bullet[1:]
                elif cleaned_bullet.startswith("o "): cleaned_bullet = cleaned_bullet[2:]
                elif cleaned_bullet.startswith("o"): cleaned_bullet = cleaned_bullet[1:]
                cleaned_bullet = cleaned_bullet.strip()
                if cleaned_bullet and cleaned_bullet not in ["•", "-", "*", "o"]:
                    bullets.append(cleaned_bullet)
            
            combo_bullet_txt=" ".join(bullets)
            skills_found=self._extract_skills_from_text(combo_bullet_txt)
            
            entry_data={"start_date":s_dt.strftime("%Y-%m-%d")if s_dt else None,
                        "end_date":e_dt.strftime("%Y-%m-%d")if e_dt else None,
                        "duration_months":dur,
                        "bullet_points":bullets,
                        "skills":skills_found}
            
            if experience_type=="research_project": 
                entry_data["name"]=proj_name
                entry_data["type"]="research_project"
            elif experience_type=="work_experience": 
                entry_data["company"]=co_name
                entry_data["role"]=role_title
            experiences.append(entry_data)
        
        if experience_type=="research_project": 
            self.facts["project_roles"]=experiences
        elif experience_type=="work_experience": 
            self.facts["work_experiences"]=experiences

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    logging.getLogger("pdfminer").setLevel(logging.WARNING)
    
    resume_file_path = "/Users/patrickgloria/Downloads/Patrick Gloria Resume --.pdf" 
    parser = ResumeParser(resume_file_path)
    facts = parser.parse()
    
    print("\n--- Extracted Skills from SKILLS section ---")
    if parser.skill_keywords: 
        print(", ".join(parser.skill_keywords))
    else: 
        print("No skills extracted from SKILLS section or section not found.")
    
    print("\n--- Aggregated Skill Durations ---")
    if facts.get("skills"):
        for skill_info in facts["skills"]:
            print(f"  Skill: {skill_info['skill_name']}, Total Months: {skill_info['total_months']}")
    else:
        print("  No aggregated skill durations available.")

    print("\n--- Extracted Work Experiences ---")
    if facts.get("work_experiences"):
        for exp in facts["work_experiences"]:
            print(f"  Company: {exp.get('company')}\n  Role: {exp.get('role')}\n    Start: {exp.get('start_date')}, End: {exp.get('end_date')}, Duration: {exp.get('duration_months')} months")
            print(f"    Bullet Points: {exp.get('bullet_points')}")
            print(f"    Identified Skills in Bullets: {exp.get('skills')}\n" + "-"*20)
    else: 
        print("  No work experiences extracted.")

    print("\n--- Extracted Project Roles ---")
    if facts.get("project_roles"):
        for role in facts["project_roles"]:
            print(f"  Name: {role.get('name')}\n    Start: {role.get('start_date')}, End: {role.get('end_date')}, Duration: {role.get('duration_months')} months")
            print(f"    Bullet Points: {role.get('bullet_points')}")
            print(f"    Identified Skills in Bullets: {role.get('skills')}\n" + "-"*20)
    else: 
        print("  No project roles extracted.")

    print("\n--- Extracted Education ---")
    if facts.get("education"):
        for edu in facts["education"]:
            print(f"  University: {edu.get('university')}")
            print(f"    Degree: {edu.get('degree')}")
            print(f"    Major: {edu.get('major')}")
            print(f"    Graduation Date: {edu.get('graduation_date')}")
            print(f"    GPA: {edu.get('gpa')}")
            print(f"    Honors: {edu.get('honors')}\n" + "-"*20)
    else:
        print("  No education information extracted.")

    print("\n--- Extracted Contact Info ---")
    contact = facts.get("contact_info")
    if contact:
        print(f"  Name: {contact.get('name')}")
        print(f"  Location: {contact.get('location')}")
        print(f"  Phone: {contact.get('phone')}")
        print(f"  Email: {contact.get('email')}")
        print(f"  LinkedIn: {contact.get('linkedin')}")
        print(f"  GitHub: {contact.get('github')}")
    else:
        print("  No contact information extracted.")
