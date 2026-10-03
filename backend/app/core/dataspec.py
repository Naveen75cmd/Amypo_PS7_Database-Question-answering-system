"""Shared domain constants for the synthetic AMYPO-style dataset.

Kept in one place so the data generator, the placement engine and the tests all
agree on the vocabulary. Swapping in AMYPO's real sample data means replacing
the generator; nothing here leaks into an answer path.
"""

from __future__ import annotations

DEPARTMENTS: tuple[str, ...] = (
    "Computer Science",
    "Information Technology",
    "Electronics and Communication",
    "Mechanical",
    "Electrical",
)

# skill_id, name, category, typical difficulty (1..5)
SKILLS: tuple[tuple[str, str, str, int], ...] = (
    ("python", "Python", "language", 2),
    ("java", "Java", "language", 3),
    ("cpp", "C++", "language", 3),
    ("javascript", "JavaScript", "language", 2),
    ("typescript", "TypeScript", "language", 3),
    ("sql", "SQL", "database", 2),
    ("datastructures", "Data Structures", "fundamentals", 3),
    ("algorithms", "Algorithms", "fundamentals", 4),
    ("oop", "Object Oriented Design", "fundamentals", 3),
    ("operatingsystems", "Operating Systems", "fundamentals", 4),
    ("networks", "Computer Networks", "fundamentals", 4),
    ("dbms", "DBMS", "database", 3),
    ("react", "React", "framework", 3),
    ("nodejs", "Node.js", "framework", 3),
    ("django", "Django", "framework", 3),
    ("springboot", "Spring Boot", "framework", 4),
    ("flask", "Flask", "framework", 2),
    ("fastapi", "FastAPI", "framework", 3),
    ("machinelearning", "Machine Learning", "ai", 4),
    ("deeplearning", "Deep Learning", "ai", 5),
    ("nlp", "Natural Language Processing", "ai", 4),
    ("pandas", "Pandas", "data", 2),
    ("numpy", "NumPy", "data", 2),
    ("docker", "Docker", "tool", 3),
    ("kubernetes", "Kubernetes", "tool", 5),
    ("git", "Git", "tool", 2),
    ("linux", "Linux", "tool", 3),
    ("aws", "AWS", "cloud", 4),
    ("azure", "Azure", "cloud", 4),
    ("testing", "Unit Testing", "tool", 2),
    ("communication", "Communication", "soft", 3),
    ("teamwork", "Teamwork", "soft", 2),
    ("problemsolving", "Problem Solving", "soft", 3),
    ("presentation", "Presentation Skills", "soft", 3),
)

SKILL_BY_ID = {s[0]: s for s in SKILLS}

# company, sector, tier, [(role, package_lpa, min_cgpa, max_backlogs,
#   min_attendance, min_projects, min_communication, allowed_departments,
#   [(skill_id, min_level, importance, is_required)])]
COMPANIES: tuple[tuple, ...] = (
    (
        "Zoho", "Product", "A", [
            ("SDE", 9.0, 7.0, 0, 75.0, 1, 3.0,
             ["Computer Science", "Information Technology"],
             [("datastructures", 3, 1.5, True), ("algorithms", 3, 1.5, True),
              ("java", 3, 1.2, True), ("sql", 2, 0.8, False),
              ("oop", 3, 1.0, True), ("problemsolving", 3, 1.0, False)]),
            ("QA Engineer", 6.5, 6.5, 1, 70.0, 0, 3.0,
             ["Computer Science", "Information Technology", "Electronics and Communication"],
             [("testing", 3, 1.4, True), ("java", 2, 1.0, False),
              ("sql", 2, 1.0, False), ("communication", 3, 1.0, False)]),
        ],
    ),
    (
        "TCS Digital", "Services", "A", [
            ("Digital Software Engineer", 7.0, 6.5, 0, 70.0, 0, 3.0,
             ["Computer Science", "Information Technology", "Electronics and Communication"],
             [("datastructures", 2, 1.2, True), ("python", 2, 1.0, True),
              ("sql", 2, 1.0, True), ("communication", 3, 1.0, False)]),
            ("Cloud Associate", 6.5, 6.0, 1, 65.0, 0, 3.0,
             ["Computer Science", "Information Technology"],
             [("aws", 2, 1.3, True), ("linux", 2, 1.0, False),
              ("networks", 2, 1.0, False), ("docker", 2, 1.0, False)]),
        ],
    ),
    (
        "Infosys", "Services", "A", [
            ("Systems Engineer", 6.5, 6.0, 1, 65.0, 0, 2.5,
             ["Computer Science", "Information Technology", "Electronics and Communication",
              "Electrical", "Mechanical"],
             [("datastructures", 2, 1.0, True), ("sql", 2, 1.0, True),
              ("communication", 3, 1.1, False), ("teamwork", 3, 0.9, False)]),
            ("Power Programmer", 9.5, 7.5, 0, 75.0, 2, 3.5,
             ["Computer Science", "Information Technology"],
             [("algorithms", 4, 1.6, True), ("datastructures", 4, 1.6, True),
              ("cpp", 3, 1.0, False), ("problemsolving", 4, 1.2, True)]),
        ],
    ),
    (
        "Freshworks", "Product", "A", [
            ("Software Engineer", 12.0, 7.5, 0, 75.0, 2, 3.5,
             ["Computer Science", "Information Technology"],
             [("datastructures", 4, 1.5, True), ("algorithms", 3, 1.4, True),
              ("javascript", 3, 1.1, True), ("react", 3, 1.1, False),
              ("git", 3, 0.8, False)]),
            ("Product Analyst", 10.0, 7.0, 0, 70.0, 1, 4.0,
             ["Computer Science", "Information Technology"],
             [("sql", 3, 1.5, True), ("python", 3, 1.2, True),
              ("presentation", 4, 1.3, True), ("communication", 4, 1.3, True)]),
        ],
    ),
    (
        "Wipro", "Services", "B", [
            ("Project Engineer", 4.5, 6.0, 2, 60.0, 0, 2.5,
             ["Computer Science", "Information Technology", "Electronics and Communication",
              "Electrical", "Mechanical"],
             [("python", 2, 1.0, True), ("communication", 2, 1.0, False)]),
        ],
    ),
    (
        "Cognizant", "Services", "B", [
            ("GenC Next Engineer", 6.75, 6.5, 0, 70.0, 1, 3.0,
             ["Computer Science", "Information Technology", "Electronics and Communication"],
             [("datastructures", 2, 1.2, True), ("java", 2, 1.0, True),
              ("sql", 2, 1.0, True)]),
        ],
    ),
    (
        "Capgemini", "Services", "B", [
            ("Analyst", 5.5, 6.0, 1, 65.0, 0, 3.0,
             ["Computer Science", "Information Technology", "Mechanical", "Electrical"],
             [("python", 2, 1.0, True), ("testing", 2, 1.0, False)]),
        ],
    ),
    (
        "Amazon", "Product", "S", [
            ("SDE-1", 18.0, 8.0, 0, 80.0, 3, 4.0,
             ["Computer Science", "Information Technology"],
             [("datastructures", 5, 1.8, True), ("algorithms", 5, 1.8, True),
              ("operatingsystems", 4, 1.2, True), ("networks", 3, 1.0, False),
              ("aws", 3, 1.0, False), ("problemsolving", 5, 1.5, True)]),
        ],
    ),
    (
        "Microsoft", "Product", "S", [
            ("Software Engineer", 20.0, 8.0, 0, 80.0, 3, 4.0,
             ["Computer Science", "Information Technology"],
             [("datastructures", 5, 1.8, True), ("algorithms", 4, 1.6, True),
              ("cpp", 4, 1.2, True), ("oop", 4, 1.2, True),
              ("problemsolving", 4, 1.3, True)]),
        ],
    ),
    (
        "Zoho Analytics", "Product", "A", [
            ("Data Engineer", 9.5, 7.0, 0, 75.0, 1, 3.0,
             ["Computer Science", "Information Technology"],
             [("sql", 4, 1.6, True), ("python", 3, 1.3, True),
              ("pandas", 3, 1.1, True), ("numpy", 3, 1.0, False),
              ("dbms", 3, 1.0, True)]),
            ("BI Developer", 8.0, 6.5, 0, 70.0, 0, 3.5,
             ["Computer Science", "Information Technology"],
             [("sql", 3, 1.5, True), ("presentation", 3, 1.1, False),
              ("communication", 3, 1.1, False)]),
        ],
    ),
    (
        "Fidelity Investments", "Finance", "A", [
            ("Software Engineer", 11.0, 7.5, 0, 75.0, 2, 3.5,
             ["Computer Science", "Information Technology"],
             [("datastructures", 3, 1.3, True), ("java", 4, 1.5, True),
              ("springboot", 3, 1.1, True), ("sql", 3, 1.1, True)]),
        ],
    ),
    (
        "Bosch", "Core", "A", [
            ("Embedded Engineer", 8.0, 7.0, 0, 75.0, 1, 3.0,
             ["Electronics and Communication", "Electrical", "Mechanical"],
             [("cpp", 4, 1.6, True), ("operatingsystems", 3, 1.2, True),
              ("linux", 3, 1.1, True), ("problemsolving", 3, 1.0, False)]),
        ],
    ),
    (
        "Tata Elxsi", "Core", "B", [
            ("Design Engineer", 6.0, 6.5, 0, 70.0, 1, 3.0,
             ["Electronics and Communication", "Mechanical", "Electrical"],
             [("cpp", 3, 1.3, True), ("oop", 3, 1.1, True),
              ("teamwork", 3, 0.9, False)]),
        ],
    ),
    (
        "Rocket Learning", "EdTech", "B", [
            ("Backend Developer", 8.5, 7.0, 0, 70.0, 1, 3.0,
             ["Computer Science", "Information Technology"],
             [("python", 3, 1.4, True), ("django", 3, 1.2, True),
              ("sql", 3, 1.1, True), ("docker", 2, 0.9, False)]),
        ],
    ),
    (
        "Verizon India", "Telecom", "A", [
            ("Network Engineer", 9.0, 7.0, 0, 75.0, 1, 3.0,
             ["Computer Science", "Information Technology", "Electronics and Communication"],
             [("networks", 4, 1.6, True), ("linux", 3, 1.2, True),
              ("python", 2, 0.9, False), ("azure", 2, 0.8, False)]),
        ],
    ),
)

INDIAN_FIRST_NAMES: tuple[str, ...] = (
    "Aarav", "Aditi", "Advait", "Aishwarya", "Akash", "Ananya", "Anjali", "Arjun",
    "Arun", "Aryan", "Bhavya", "Charan", "Deepa", "Deepak", "Devika", "Dhruv",
    "Divya", "Ganesh", "Gayathri", "Harini", "Harish", "Ishaan", "Janani", "Karthik",
    "Kavya", "Keerthana", "Kiran", "Lakshmi", "Madhav", "Meera", "Mohan", "Nandhini",
    "Naveen", "Nikhil", "Nithya", "Pooja", "Pranav", "Priya", "Rahul", "Rajesh",
    "Ravi", "Rohit", "Sahana", "Sanjay", "Shalini", "Shruti", "Sneha", "Suresh",
    "Swathi", "Tanvi", "Uma", "Varun", "Vignesh", "Vikram", "Yamini",
)

INDIAN_LAST_NAMES: tuple[str, ...] = (
    "Agarwal", "Balaji", "Bhat", "Chandra", "Das", "Desai", "Gopal", "Gupta",
    "Hegde", "Iyer", "Jain", "Kannan", "Krishnan", "Kumar", "Menon", "Mishra",
    "Murthy", "Nair", "Narayanan", "Patel", "Pillai", "Prasad", "Raghavan",
    "Raju", "Raman", "Rao", "Reddy", "Sankaran", "Sharma", "Shetty", "Singh",
    "Subramanian", "Swamy", "Varma", "Venkatesh", "Verma",
)

# course_id, title, department, credits, semester
COURSES: tuple[tuple[str, str, str, int, int], ...] = (
    ("CS301", "Data Structures", "Computer Science", 4, 3),
    ("CS302", "Design and Analysis of Algorithms", "Computer Science", 4, 3),
    ("CS303", "Database Management Systems", "Computer Science", 3, 3),
    ("CS304", "Operating Systems", "Computer Science", 4, 4),
    ("CS305", "Computer Networks", "Computer Science", 3, 4),
    ("CS306", "Object Oriented Programming", "Computer Science", 3, 2),
    ("CS307", "Machine Learning", "Computer Science", 4, 5),
    ("CS308", "Software Engineering", "Computer Science", 3, 5),
    ("IT401", "Web Technologies", "Information Technology", 3, 4),
    ("IT402", "Cloud Computing", "Information Technology", 3, 5),
    ("IT403", "Data Analytics with Python", "Information Technology", 3, 4),
    ("EC501", "Microcontrollers", "Electronics and Communication", 4, 5),
    ("EC502", "Signals and Systems", "Electronics and Communication", 4, 3),
    ("ME601", "Thermodynamics", "Mechanical", 4, 3),
    ("EE701", "Power Systems", "Electrical", 4, 4),
    ("HS101", "Professional Communication", "Humanities", 2, 1),
    ("HS102", "Placement Preparation Workshop", "Humanities", 2, 6),
)

DAY_NAMES: tuple[str, ...] = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday")
TIME_SLOTS: tuple[tuple[str, str], ...] = (
    ("09:00", "10:00"),
    ("10:00", "11:00"),
    ("11:15", "12:15"),
    ("13:30", "14:30"),
    ("14:30", "15:30"),
)
ROOM_PREFIXES: tuple[str, ...] = ("LH", "Lab", "Block-A", "Block-C")
FACULTY_NAMES: tuple[str, ...] = (
    "Dr. Meenakshi Sundaram", "Prof. Rajesh Kannan", "Dr. Priya Venkatesh",
    "Prof. Anand Krishnan", "Dr. Sudha Raman", "Prof. Vikram Nair",
    "Dr. Latha Subramanian", "Prof. Ganesh Iyer", "Dr. Rekha Prasad",
    "Prof. Suresh Babu",
)
