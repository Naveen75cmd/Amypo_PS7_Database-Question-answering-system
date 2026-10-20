# Placement Cell Internals (Staff Only)

Internal working notes for the Training and Placement Officer and department
placement coordinators. Marked staff-visible: students see company criteria
through the placement console, never this document.

## 1. Score weights

The candidate ranking score is a weighted sum of CGPA, attendance, verified
skills, communication score and project count. Default weights are 0.35, 0.15,
0.30, 0.10 and 0.10. Only an administrator may change the weights, and every
change is written to the audit log with the previous and new values.

## 2. Company criteria

Criteria are stored per company-role pair: minimum CGPA, maximum backlogs,
minimum attendance, required skills with a minimum level, and an optional
department allow-list. Criteria are versioned; editing a criterion does not
rewrite history, it adds a new version.

A coordinator may edit criteria for the companies they are assigned to. Any
other edit is refused and audited.

## 3. Shortlist workflow

1. The company sends a role description.
2. The coordinator encodes the criteria and runs the cohort match.
3. The match result is reviewed for fairness: the fairness report compares
   selection rates across departments and flags a gap above ten percentage
   points.
4. The shortlist is released to students as an eligibility result, with every
   failing criterion named.

## 4. Known biases and mitigations

The ranker prefers higher CGPA, which correlates with the department. The
fairness check is therefore run before every shortlist release, and the
criterion-level explanation is always shown so a rejection is never a black
box.

## 5. Off-limits data

Do not paste recruiter contact details, salary negotiations or offer letters
into the question box. Those are not in the corpus and the assistant will
abstain rather than guess.
