e#!/usr/bin/env python3
"""
Utility script to generate and customize skill durations based on resume data.

This script:
1. Parses the user's resume
2. Extracts skill durations based on work experience
3. Lets the user review and edit these durations
4. Saves the result to skill_durations.yaml for use by the LinkedIn bot
"""
import argparse
import yaml
import os
import sys
import logging
from auto_apply_bot.resume_parser import parse_resume, SKILL_RELATIONSHIPS

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description='Generate skill durations from resume.')
    parser.add_argument('--resume', '-r', 
                        required=True, 
                        help='Path to resume PDF file')
    parser.add_argument('--output', '-o', 
                        default='skill_durations.yaml',
                        help='Output YAML file (default: skill_durations.yaml)')
    parser.add_argument('--force', '-f', 
                        action='store_true',
                        help='Overwrite existing file without prompting')
    parser.add_argument('--verbose', '-v',
                        action='store_true',
                        default=True,
                        help='Show detailed calculation for each skill (default: True)')
    parser.add_argument('--csv',
                        action='store_true',
                        help='Also export details to CSV file (skill_durations_details.csv)')
    return parser.parse_args()

def format_skill_details(skill, data):
    """Format detailed information about a skill's duration calculation."""
    years = data.get("years", 0)
    if years is None:
        years = 0
    months = data.get("months", 0)
    roles = data.get("roles", [])
    sources = data.get("source", [])
    
    # Clean up role names and filter blanks
    cleaned_roles = []
    for role in roles:
        # Skip empty entries and generic placeholders
        if not role.strip() or role == "Project: " or role == "Project: Unknown":
            continue
            
        # Remove "Project: " prefix if present
        if role.startswith("Project: "):
            # Only keep the actual name part
            project_name = role[9:].strip()  # Skip the "Project: " prefix (9 chars)
            if project_name and not project_name.startswith("Project "):  # Not a generic "Project N"
                cleaned_roles.append(project_name)
            elif project_name:  # It's a generic "Project N" but we'll show it anyway
                cleaned_roles.append(project_name)
        else:
            # For non-project roles, keep as is
            cleaned_roles.append(role)
    
    # Format roles and sources
    roles_str = ", ".join(cleaned_roles) if cleaned_roles else "—"
    sources_str = ", ".join(sources) if sources else "unknown"
    
    # Create the formatted string
    details = (
        f"\n{skill.upper()}\n"
        f"  ├─ total months ............ {months}\n"
        f"  ├─ equivalent years ........ {years:.1f}\n"
        f"  ├─ calculation source ...... {sources_str}\n"
        f"  └─ from roles/projects ..... {roles_str}\n"
    )
    
    return details

def get_user_input(prompt, default=None):
    """Get user input with a default value."""
    if default is not None:
        user_input = input(f"{prompt} [{default}]: ")
        return user_input if user_input.strip() else default
    else:
        return input(f"{prompt}: ")

def main(args=None):
    """
    Main function to generate and save skill durations.
    
    Args:
        args: Optional pre-parsed arguments (for calling from another script)
              If None, will parse from command line
    """
    if args is None:
        args = parse_args()
    
    # Check if resume exists
    if not os.path.exists(args.resume):
        logger.error(f"Resume file not found: {args.resume}")
        sys.exit(1)
    
    # Check if output file already exists
    if os.path.exists(args.output) and not args.force:
        overwrite = get_user_input(f"File {args.output} already exists. Overwrite? (y/n)", "n")
        if overwrite.lower() != 'y':
            logger.info("Aborted by user.")
            sys.exit(0)
    
    # Parse resume
    logger.info(f"Parsing resume: {args.resume}")
    try:
        resume_data = parse_resume(args.resume)
    except Exception as e:
        logger.error(f"Error parsing resume: {e}")
        sys.exit(1)
    
    # Get skill durations from resume data
    skill_durations = resume_data.get("skill_durations", {})
    if not skill_durations:
        logger.warning("No skill durations found in resume.")
        sys.exit(1)
    
    # Prepare data structures for YAML
    yaml_data = {}
    skills_with_details = {}
    
    # Group skills by source
    skills_by_source = {
        "experience": [],    # Skills from direct work experience
        "project": [],       # Skills from projects/research
        "estimated": [],     # Skills estimated from related skills
        "skills_only": []    # Skills only found in skills section
    }
    
    # Collect skills with their durations, roles, and sources
    for skill, data in skill_durations.items():
        years = data.get("years", 0)
        roles = data.get("roles", [])
        sources = data.get("source", [])
        
        # Store details for display
        skills_with_details[skill] = (years, roles, sources)
        
        # Group by source (primary source only)
        if sources:
            primary_source = sources[0]
            if primary_source in skills_by_source:
                skills_by_source[primary_source].append(skill)
            else:
                skills_by_source["skills_only"].append(skill)
    
    # Sort skill groupings
    for source in skills_by_source:
        skills_by_source[source].sort()
    
    # Display to user for review and editing
    print("\n===== DETECTED SKILL DURATIONS =====")
    print("Based on your resume, we've detected the following skill durations.")
    print("You can customize these values, or press Enter to accept the defaults.")
    
    edited_durations = {}
    
    # Prepare CSV data if requested
    csv_data = []
    if args.csv:
        csv_data.append(["Skill", "Years", "Months", "Source", "Roles"])
    
    # Process work experience skills first
    if skills_by_source["experience"]:
        print("\n## Skills from Work Experience ##")
        for skill in skills_by_source["experience"]:
            # Get skill details
            years, roles, sources = skills_with_details[skill]
            data = skill_durations[skill]
            
            # Show detailed calculation if verbose
            if args.verbose:
                print(format_skill_details(skill, data))
            
            # Add to CSV data
            if args.csv:
                csv_data.append([
                    skill, 
                    str(data.get("years", 0)), 
                    str(data.get("months", 0)), 
                    "|".join(data.get("source", [])), 
                    "|".join(data.get("roles", []))
                ])
            
            # Prompt for input
            roles_str = ", ".join(roles) if roles else "No specific role"
            prompt = f"{skill}: {years:.1f} years (from {roles_str})"
            new_value = get_user_input(prompt, str(years))
            
            try:
                edited_durations[skill] = max(0, float(new_value))
            except ValueError:
                logger.warning(f"Invalid value '{new_value}' for {skill}. Using default: {years}")
                edited_durations[skill] = years
    
    # Process project skills next
    if skills_by_source["project"]:
        print("\n## Skills from Projects/Research ##")
        for skill in skills_by_source["project"]:
            # Get skill details
            years, roles, sources = skills_with_details[skill]
            data = skill_durations[skill]
            
            # Show detailed calculation if verbose
            if args.verbose:
                print(format_skill_details(skill, data))
            
            # Add to CSV data
            if args.csv:
                csv_data.append([
                    skill, 
                    str(data.get("years", 0)), 
                    str(data.get("months", 0)), 
                    "|".join(data.get("source", [])), 
                    "|".join(data.get("roles", []))
                ])
            
            # Prompt for input
            roles_str = ", ".join(roles) if roles else "No specific role"
            prompt = f"{skill}: {years:.1f} years (from {roles_str})"
            new_value = get_user_input(prompt, str(years))
            
            try:
                edited_durations[skill] = max(0, float(new_value))
            except ValueError:
                logger.warning(f"Invalid value '{new_value}' for {skill}. Using default: {years}")
                edited_durations[skill] = years
    
    # Process estimated skills next
    if skills_by_source["estimated"]:
        print("\n## Skills Estimated from Related Skills ##")
        for skill in skills_by_source["estimated"]:
            # Get skill details
            years, roles, sources = skills_with_details[skill]
            data = skill_durations[skill]
            
            # Show detailed calculation if verbose
            if args.verbose:
                print(format_skill_details(skill, data))
            
            # Add to CSV data
            if args.csv:
                csv_data.append([
                    skill, 
                    str(data.get("years", 0)), 
                    str(data.get("months", 0)), 
                    "|".join(data.get("source", [])), 
                    "|".join(data.get("roles", []))
                ])
            
            # Prompt for input
            prompt = f"{skill}: {years:.1f} years (estimated from related skills)"
            new_value = get_user_input(prompt, str(years))
            
            try:
                edited_durations[skill] = max(0, float(new_value))
            except ValueError:
                logger.warning(f"Invalid value '{new_value}' for {skill}. Using default: {years}")
                edited_durations[skill] = years
    
    # Finally, prompt for skills that only appear in skills section
    if skills_by_source["skills_only"]:
        print("\n## Skills Only Listed in Skills Section ##")
        print("Please enter years of experience for these skills that appear only in your Skills section:")
        
        for skill in skills_by_source["skills_only"]:
            # Get skill details
            years, roles, sources = skills_with_details[skill]
            data = skill_durations[skill]
            
            # Show detailed calculation if verbose
            if args.verbose and data.get("years") is not None:  # Only show details if not None
                print(format_skill_details(skill, data))
            
            # Add to CSV data if years is not None
            if args.csv and data.get("years") is not None:
                csv_data.append([
                    skill, 
                    str(data.get("years", 0)), 
                    str(data.get("months", 0)), 
                    "|".join(data.get("source", [])), 
                    "|".join(data.get("roles", []))
                ])
            
            # If years is None, we need to prompt for it
            if years is None:
                prompt = f"{skill} only appears in Skills section. Years of experience (or 0 to exclude):"
                new_value = get_user_input(prompt, "0")
            else:
                prompt = f"{skill}: {years:.1f} years (skills section only)"
                new_value = get_user_input(prompt, str(years))
                
            try:
                years_value = float(new_value)
                # Only include skills with > 0 years
                if years_value > 0:
                    edited_durations[skill] = years_value
                    
                    # Add to CSV if it's a new skill with manually entered duration
                    if args.csv and data.get("years") is None and years_value > 0:
                        csv_data.append([
                            skill, 
                            str(years_value), 
                            str(int(years_value * 12)), 
                            "skills_only|user_defined", 
                            "User-entered"
                        ])
                else:
                    logger.info(f"Excluding {skill} (0 years entered)")
            except ValueError:
                if years is not None:
                    logger.warning(f"Invalid value '{new_value}' for {skill}. Using default: {years}")
                    edited_durations[skill] = years
                else:
                    logger.info(f"Excluding {skill} (invalid entry)")
    
    # Save to YAML file
    with open(args.output, 'w') as f:
        yaml.dump(edited_durations, f, default_flow_style=False)
    
    logger.info(f"Skill durations saved to {args.output}")
    print(f"\nSkill durations have been saved to {args.output}.")
    print(f"Total skills: {len(edited_durations)}")
    print("The LinkedIn bot will use these values when answering numeric experience questions.")
    
    # Save CSV data if requested
    if args.csv and csv_data:
        import csv
        csv_filename = "skill_durations_details.csv"
        with open(csv_filename, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerows(csv_data)
        logger.info(f"Skill duration details saved to {csv_filename}")
        print(f"Detailed skill information saved to {csv_filename}")

if __name__ == "__main__":
    main()
