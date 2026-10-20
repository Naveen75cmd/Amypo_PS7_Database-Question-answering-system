# Security and Access Runbook (Admin Only)

Operational notes for the system administrator. Documents under
`data/raw/admin/` are visible only to the admin role; staff and student
sessions are filtered before ranking, so this text cannot reach them even as a
low-ranked passage.

## 1. Roles

Three human roles and one machine role exist. Students read public documents
and their own records. Staff read public and staff documents plus the records of
students in their assigned departments, and may run cohort placement queries,
which are audited. Admin reads everything, manages accounts, approves
ingestion, changes router settings and scoring weights, and reads the audit log.

The `eval` role is the organisers' evaluation harness: read-only, public
documents only, no personal records under any circumstances.

## 2. Session handling

Access tokens are short-lived (fifteen minutes) and signed with a key that never
enters the repository. Refresh tokens are revocable rows; only their SHA-256
hash is stored. Rotating a refresh token invalidates the previous one, and
presenting a rotated token again revokes every session for that account, on the
assumption that a leaked token is being replayed.

Disabling an account, resetting its password or changing its role ends that
account's sessions immediately.

## 3. Audit retention

Every login, failed login, denied action, cohort query, personal-data read and
ingestion run is written to `audit_log` with the actor, role, scope and client
address. Rows are append-only from the application's point of view: there is no
delete endpoint, and retention is ninety days in the demo dataset.

## 4. Secret handling

`AMYPO_JWT_SECRET` is set through the environment, never committed. If it is
unset the backend generates a random key per process, which is safe but logs
every user out on restart. Passwords are bcrypt hashes; the demo accounts share
a documented password and are only seeded when `AMYPO_DEMO_MODE` is true.

## 5. Incident checklist

1. Disable the affected account and confirm its sessions are gone.
2. Read the audit log for that actor and confirm the scope of access.
3. Rotate `AMYPO_JWT_SECRET` if the signing key may have leaked; this ends all
   sessions at once.
4. Re-ingest the corpus if a document's visibility was wrong, and confirm the
   chunk scopes in MySQL match the directory the document lives in.
