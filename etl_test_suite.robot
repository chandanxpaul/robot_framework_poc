*** Settings ***
Documentation     ETL validation suite: completeness, integrity, and row-by-row reconciliation
...               between source.db and target.db.
Library           DatabaseLibrary
Resource          resources.robot
Library           ETLCustomLib.py
Test Setup        Open ETL Database Connections
Test Teardown     Disconnect From All Databases

*** Test Cases ***
ETL Completeness Check
    [Documentation]    Source and target ``users`` tables must contain the same number of rows.
    ...                A mismatch indicates missing or extra records after the ETL load.
    ${source_row_count}=    Row Count    SELECT * FROM users    alias=${SOURCE_DB_ALIAS}
    ${target_row_count}=    Row Count    SELECT * FROM users    alias=${TARGET_DB_ALIAS}
    Log    Source users row count: ${source_row_count}
    Log    Target users row count: ${target_row_count}
    Should Be Equal As Integers    ${source_row_count}    ${target_row_count}
    ...    msg=Completeness failure: source has ${source_row_count} user row(s) but target has ${target_row_count}.

Data Integrity Check
    [Documentation]    Target ``users.email`` must never be NULL.
    ...                Counts NULL emails in target and asserts the count is zero.
    ${null_email_count}=    Query
    ...    SELECT COUNT(*) FROM users WHERE email IS NULL
    ...    alias=${TARGET_DB_ALIAS}
    ${nulls}=    Set Variable    ${null_email_count[0][0]}
    Log    Target users with NULL email: ${nulls}
    Should Be Equal As Integers    ${nulls}    0
    ...    msg=Integrity failure: found ${nulls} user row(s) with NULL email in target.

Row-by-Row Reconciliation Check
    [Documentation]    Compare full ``users`` result sets from source and target.
    ...                Fails if any row is missing or any column value differs.
    Compare Source And Target Dataframes    SELECT * FROM users ORDER BY id

*** Keywords ***
Open ETL Database Connections
    [Documentation]    Establish connections to both source and target databases before each test.
    Connect To Source Database
    Connect To Target Database
