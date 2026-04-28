import json
import re
import os

def get_resume_files():
    # Find all JSON files that look like resumes
    files = [f for f in os.listdir('.') if f.endswith('.json') and f.startswith('resume_')]
    return files

def calculate_ats_score(data_path, jd_path):
    # Load your resume data
    try:
        with open(data_path, 'r') as f:
            resume = json.load(f)
    except Exception as e:
        print(f"Error loading {data_path}: {e}")
        return
    
    # Load Job Description
    try:
        with open(jd_path, 'r', encoding='utf-8') as f:
            jd = f.read().lower()
    except FileNotFoundError:
        print(f"Error: {jd_path} not found. Please create it and paste the Job Description.")
        return

    # Extract all possible keywords from the resume
    resume_keywords = set()
    
    # 1. From Skills
    for category in resume.get('skills', {}):
        for skill in resume['skills'][category]:
            resume_keywords.add(skill.lower())
            
    # 2. From Experience Keywords
    for exp in resume.get('experience', []):
        for kw in exp.get('keywords', []):
            resume_keywords.add(kw.lower())
            
    # 3. From Project Keywords
    for proj in resume.get('projects', []):
        for kw in proj.get('keywords', []):
            resume_keywords.add(kw.lower())

    # Find matches in JD
    matches = []
    jd_words = set(re.findall(r'\b\w{2,}\b', jd))
    
    for kw in resume_keywords:
        if kw in jd:
            matches.append(kw)
            
    # Suggestions for common tech not found
    common_tech = ["react", "node", "aws", "docker", "kubernetes", "sql", "nosql", "python", "java", "typescript", "machine learning", "api", "git", "rest", "backend", "frontend"]
    missing = [tech for tech in common_tech if tech in jd and tech not in [m.lower() for m in matches]]

    # Scoring (Visual representation)
    final_score = min(len(matches) * 7, 100) 

    name = resume.get('personal_info', {}).get('name', 'Unknown')

    print("\n" + "="*40)
    print(f"   ATS CHECKER: {name.upper()}")
    print("="*40)
    print(f"MATCH SCORE: {final_score}%")
    print(f"Matched Keywords: {', '.join(matches[:10])}...")
    
    if missing:
        print("\n[!] KEYWORDS MISSING FROM RESUME:")
        print(f"These are in the JD but not in your data: {', '.join(missing)}")
    
    print("\n" + "-"*40)
    print("ACTION: Update your JSON to include missing keywords!")
    print("="*40)

if __name__ == "__main__":
    resume_files = get_resume_files()
    
    if not resume_files:
        print("No resume files found! (Files must start with 'resume_' and end with '.json')")
    else:
        print("\nSelect a resume to check:")
        for i, f in enumerate(resume_files):
            print(f"{i+1}. {f}")
        
        try:
            choice = int(input("\nEnter number: ")) - 1
            if 0 <= choice < len(resume_files):
                calculate_ats_score(resume_files[choice], 'job_description.txt')
            else:
                print("Invalid selection.")
        except ValueError:
            print("Please enter a number.")
