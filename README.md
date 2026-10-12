# Robot Framework ETL Testing POC

A hands-on proof of concept that uses **Robot Framework** to validate an ETL (Extract, Transform, Load) pipeline between two SQLite databases.

If you are new to Robot Framework: think of `.robot` files as readable test scripts written mostly in plain English. Keywords are the building blocks (like functions). Some keywords come from libraries (`DatabaseLibrary`, our custom `ETLCustomLib`), and some you define yourself in resource files.

---

## What this project demonstrates

After a mock ETL load, we verify three classic data-quality checks:

| Check | Question it answers | Expected result with seeded data |
|---|---|---|
| **Completeness** | Did every source row make it to target? | FAIL (4 rows deleted from target) |
| **Integrity** | Are required fields valid (no NULL emails)? | FAIL (7 NULL emails in target) |
| **Reconciliation** | Do source and target match row-by-row? | FAIL (missing rows + status/email diffs) |

The failures are **intentional**. The goal of this POC is to show how Robot Framework reports clear ETL defects—not to make all tests pass.

---

## Project layout

```text
robot_framework_poc/
├── README.md                 # This file
├── requirements.txt          # Python dependencies
├── setup_mock_dbs.py         # Creates source.db / target.db with seeded defects
├── source.db                 # "Upstream" / source system (generated)
├── target.db                 # "Warehouse" / target system (generated)
├── resources.robot           # Shared DB connection keywords & variables
├── ETLCustomLib.py           # Custom Python library for DataFrame comparison
├── etl_test_suite.robot      # The Robot Framework test suite
└── results/                  # HTML/XML reports produced by `robot` (after a run)
```

### How the pieces fit together

```text
setup_mock_dbs.py  -->  source.db + target.db
                              |
                              v
etl_test_suite.robot
   |-- uses resources.robot          (connect / disconnect SQLite)
   |-- uses DatabaseLibrary          (SQL row counts & queries)
   '-- uses ETLCustomLib.py          (Pandas row-by-row compare)
```

---

## Prerequisites

- Python 3.10+ recommended
- Ability to create a virtual environment (`python3 -m venv`)

---

## Quick start

### 1. Create and activate a virtual environment

```bash
cd robot_framework_poc
python3 -m venv .venv

# macOS / Linux
source .venv/bin/activate

# Windows (PowerShell)
# .venv\Scripts\Activate.ps1
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

| Package | Purpose |
|---|---|
| `robotframework` | Test runner and core language |
| `robotframework-databaselibrary` | Keywords like `Connect To Database`, `Row Count`, `Query` |
| `pandas` | Tabular comparison inside `ETLCustomLib` |

### 3. Generate the mock databases

```bash
python setup_mock_dbs.py
# or: ./setup_mock_dbs.py
```

This creates (or recreates):

- `source.db` — clean `users` rows
- `target.db` — the same rows, then intentional defects are applied

**Defaults:** 200 records, 4 deleted rows, 7 NULL emails, 5 status flips, seed `42`.

Because a fixed random seed is used, re-running with the same flags produces the **same** defect IDs every time.

#### Configurable record & defect counts

| Flag | Meaning | Default |
|---|---|---|
| `-n` / `--records` | Rows inserted into both DBs | `200` |
| `--delete-rows` | Completeness defects (rows removed from target) | `4` |
| `--null-emails` | Integrity defects (`email` set to NULL in target) | `7` |
| `--status-changes` | Reconciliation defects (status flipped in target) | `5` |
| `--seed` | RNG seed for reproducible data/defect IDs | `42` |

```bash
# Larger dataset with more defects
python setup_mock_dbs.py --records 500 --delete-rows 10 --null-emails 15 --status-changes 8

# Clean target (no intentional defects) — useful to see all Robot tests PASS
python setup_mock_dbs.py --records 200 --delete-rows 0 --null-emails 0 --status-changes 0

# Show every option
python setup_mock_dbs.py --help
```

Defect rows are chosen **without overlap**, so this must hold:

```text
delete-rows + null-emails + status-changes  <=  records
```

You can also change the `DEFAULT_*` constants near the top of `setup_mock_dbs.py` if you prefer editing defaults instead of passing flags.

### 4. Run the Robot Framework suite

```bash
robot --outputdir results etl_test_suite.robot
```

Open the reports:

- `results/report.html` — high-level pass/fail summary
- `results/log.html` — step-by-step keyword log (best place to debug)

With the seeded data you should see **3 tests, 0 passed, 3 failed**.

---

## Robot Framework concepts used here (beginner guide)

### Settings, Variables, Keywords, Test Cases

A `.robot` file is split into sections:

- `*** Settings ***` — imports libraries/resources, suite docs, setup/teardown
- `*** Variables ***` — reusable values like `${SOURCE_DB}`
- `*** Test Cases ***` — the actual tests
- `*** Keywords ***` — reusable steps (like helper functions)

### Libraries vs resources

| Type | Example | What it provides |
|---|---|---|
| Library | `DatabaseLibrary`, `ETLCustomLib.py` | Keywords implemented in Python |
| Resource | `resources.robot` | Shared variables + keywords written in Robot syntax |

### Python method → Robot keyword naming

Robot Framework converts `snake_case` Python methods into Title Case keywords:

| Python method | Robot keyword you call |
|---|---|
| `compare_source_and_target_dataframes` | `Compare Source And Target Dataframes` |
| `connect_to_database` (from DatabaseLibrary) | `Connect To Database` |

### Test Setup / Teardown

In `etl_test_suite.robot`:

- **Test Setup** runs before every test → open source + target DB connections
- **Test Teardown** runs after every test → disconnect safely

This keeps each test isolated and avoids leftover connections.

### Aliases (why we use them)

`DatabaseLibrary` can keep more than one connection open if you give each an alias (`source`, `target`). Later keywords pass `alias=${SOURCE_DB_ALIAS}` so Robot knows which database to query.

---

## Test suite details (`etl_test_suite.robot`)

### 1. ETL Completeness Check

Uses DatabaseLibrary `Row Count` on both databases and asserts the counts are equal.

- Seeded failure: source = **200**, target = **196**

### 2. Data Integrity Check

Runs SQL against target:

```sql
SELECT COUNT(*) FROM users WHERE email IS NULL
```

Asserts the count is `0`.

- Seeded failure: **7** NULL emails

### 3. Row-by-Row Reconciliation Check

Calls the custom keyword:

```robot
Compare Source And Target Dataframes    SELECT * FROM users ORDER BY id
```

`ETLCustomLib` loads both result sets into Pandas DataFrames and reports:

- rows only in source / only in target
- per-column value mismatches (when an `id` column exists)

- Seeded failure: 4 missing rows + email/status value diffs

---

## Custom library (`ETLCustomLib.py`)

This is a **custom Robot Framework library**: a Python class whose public methods become keywords.

Important class attributes:

- `ROBOT_LIBRARY_SCOPE = "GLOBAL"` — one library instance shared across the suite
- Public method `compare_source_and_target_dataframes(query)` — the keyword used by Test Case 3

On mismatch it:

1. Prints a human-readable summary (visible in the console and log)
2. Raises `AssertionError` so Robot marks the test as **FAIL**

On a perfect match it logs a success message.

---

## Resource file (`resources.robot`)

Centralizes connection details so tests stay clean:

| Keyword | Purpose |
|---|---|
| `Connect To Source Database` | Open `source.db` with alias `source` |
| `Connect To Target Database` | Open `target.db` with alias `target` |
| `Disconnect From All Databases` | Close both connections (errors ignored if already closed) |

Database paths use `${CURDIR}` so they resolve relative to `resources.robot`, no matter which directory you launch `robot` from.

---

## Querying the databases manually

```bash
sqlite3 source.db "SELECT COUNT(*) FROM users;"
sqlite3 target.db "SELECT COUNT(*) FROM users;"

sqlite3 -header -column target.db \
  "SELECT id, name, email, status FROM users WHERE email IS NULL;"
```

Compare side by side:

```bash
sqlite3 target.db
```

```sql
ATTACH 'source.db' AS src;

SELECT s.id
FROM src.users s
LEFT JOIN users t ON s.id = t.id
WHERE t.id IS NULL;
```

---

## Typical workflow when changing tests

1. Edit `setup_mock_dbs.py` if you need different seed data / defect counts
2. Re-run `python setup_mock_dbs.py`
3. Edit `etl_test_suite.robot` (or add new keywords in `resources.robot` / `ETLCustomLib.py`)
4. Run `robot --outputdir results etl_test_suite.robot`
5. Inspect `results/log.html`

---

## Making the tests pass (optional experiment)

Regenerate the databases with all defect counts set to zero, then re-run the suite:

```bash
python setup_mock_dbs.py --delete-rows 0 --null-emails 0 --status-changes 0
robot --outputdir results etl_test_suite.robot
```

Both databases will contain identical data, so all three tests should PASS.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `ModuleNotFoundError: pandas` / `robot` | Dependencies not installed or venv not active | `source .venv/bin/activate && pip install -r requirements.txt` |
| `Database not found: .../source.db` | Mock DBs not generated | Run `python setup_mock_dbs.py` |
| Connection / alias errors | Setup keyword did not run or alias typo | Confirm `Test Setup` and `${SOURCE_DB_ALIAS}` / `${TARGET_DB_ALIAS}` |
| All 3 tests fail | Expected with seeded defects | Open `results/log.html` to inspect messages |

---

## Useful Robot CLI flags

```bash
# Run the full suite
robot --outputdir results etl_test_suite.robot

# Run a single test by name
robot --outputdir results --test "Data Integrity Check" etl_test_suite.robot

# More console detail
robot --outputdir results --loglevel DEBUG etl_test_suite.robot
```
