import json
import re
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# A comprehensive master list of technology keywords to look for in any JD
MASTER_TECH_LIST = {
    "python", "javascript", "typescript", "java", "c++", "c#", "react", "next.js", "vite", "vue", "angular",
    "node.js", "express", "fastapi", "flask", "django", "spring boot", "postgresql", "mongodb", "mysql",
    "sqlite", "supabase", "firebase", "aws", "gcp", "azure", "docker", "kubernetes", "git", "github actions",
    "ci/cd", "rest api", "graphql", "pytorch", "tensorflow", "scikit-learn", "opencv", "machine learning",
    "deep learning", "nlp", "ai", "llm", "gemini", "openai", "terraform", "ansible", "linux", "html", "css",
    "tailwind", "bootstrap", "redux", "async python", "pydantic", "uvicorn", "cloudinary", "vertex ai",
    "data structures", "algorithms", "oops", "distributed systems", "microservices", "agile", "scrum",
    "pyspark", "tableau", "power bi", "hive", "hadoop", "r", "azure databricks"
}

def get_resume_files():
    return [f for f in os.listdir(SCRIPT_DIR) if f.endswith('.json') and f.startswith('resume_')]

def calculate_ats_score(data_filename, jd_filename):
    data_path = os.path.join(SCRIPT_DIR, data_filename)
    jd_path = os.path.join(SCRIPT_DIR, jd_filename)
    # 1. Load Data
    try:
        with open(data_path, 'r') as f:
            resume = json.load(f)
        with open(jd_path, 'r', encoding='utf-8') as f:
            jd_raw = f.read()
            jd_text = jd_raw.lower()
    except Exception as e:
        print(f"Error: {e}")
        return

    # Extract JD title/header for display
    jd_lines = [line.strip() for line in jd_raw.splitlines() if line.strip()]
    company = "Unknown Company"
    role = "Unknown Role"

    if jd_lines:
        # Extract Company
        company_line = next((line for line in jd_lines if line.lower().startswith("company:")), None)
        if company_line:
            company = company_line.split(":", 1)[1].strip()
        else:
            about_line = next((line for line in jd_lines if line.lower().startswith("about ")), None)
            if about_line:
                company = about_line.split(" ", 1)[1].strip()

        # Extract Role
        role_line = next((line for line in jd_lines if line.lower().startswith("job title:") or line.lower().startswith("role:")), None)
        if role_line:
            role = role_line.split(":", 1)[1].strip()
        else:
            first_line = jd_lines[0]
            if first_line.lower().startswith("position summary") and len(jd_lines) > 1:
                second_line = jd_lines[1]
                if "," in second_line:
                    role = second_line.split(",")[0].strip()
                else:
                    role = second_line
            else:
                role = first_line

        # Clean up prefixes like "As a " / "As an "
        if role.lower().startswith("as a "):
            role = role[5:].strip()
        elif role.lower().startswith("as an "):
            role = role[6:].strip()

    if len(company) > 35:
        company = company[:32] + "..."
    if len(role) > 40:
        role = role[:37] + "..."

    # 2. Extract Keywords from Resume Data (JSON)
    # We look through every value in the JSON for keywords
    def extract_all_values(obj):
        values = []
        if isinstance(obj, dict):
            for v in obj.values():
                values.extend(extract_all_values(v))
        elif isinstance(obj, list):
            for item in obj:
                values.extend(extract_all_values(item))
        else:
            values.append(str(obj).lower())
        return values

    all_resume_text = " ".join(extract_all_values(resume))
    
    # 3. Find What the Job Wants (Technical Keywords in JD)
    # We scan the JD for any word that is in our MASTER_TECH_LIST
    required_keywords = set()
    for tech in MASTER_TECH_LIST:
        # Use regex to find whole word matches
        if re.search(rf'\b{re.escape(tech)}\b', jd_text):
            required_keywords.add(tech)

    # 4. Compare and Score
    matched = []
    missing = []
    
    for kw in required_keywords:
        if kw in all_resume_text:
            matched.append(kw)
        else:
            missing.append(kw)

    # Scoring Logic
    if not required_keywords:
        score = 0
    else:
        score = int((len(matched) / len(required_keywords)) * 100)

    # 5. Display Results
    name = resume.get('personal_info', {}).get('name', 'User')
    print("\n" + "="*45)
    print(f"   ATS SCANNER: {name.upper()}")
    print("="*45)
    print(f"COMPANY      : {company}")
    print(f"ROLE         : {role}")
    print(f"OVERALL MATCH: {score}%")
    print(f"Matched ({len(matched)}): {', '.join(matched)}")
    
    if missing:
        print("\n[!] MISSING KEYWORDS (Add these to improve score):")
        print(f"  - " + "\n  - ".join(missing))
    
    print("\n" + "-"*45)
    print("TIP: Tailor your projects in the JSON to include the missing tags.")
    print("="*45)

if __name__ == "__main__":
    resumes = get_resume_files()
    if not resumes:
        print("No resume_*.json files found.")
    else:
        print("\nChoose Resume:")
        for i, f in enumerate(resumes):
            print(f"{i+1}. {f}")
        
        try:
            idx = int(input("\nEnter choice: ")) - 1
            calculate_ats_score(resumes[idx], 'job_description.txt')
        except:
            print("Invalid input.")
