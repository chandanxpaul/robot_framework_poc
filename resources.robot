*** Settings ***
Library    DatabaseLibrary

*** Variables ***
${DB_MODULE}           sqlite3
${SOURCE_DB}           ${CURDIR}${/}source.db
${TARGET_DB}           ${CURDIR}${/}target.db
${SOURCE_DB_ALIAS}     source
${TARGET_DB_ALIAS}     target

*** Keywords ***
Connect To Source Database
    [Documentation]    Connect to the source SQLite database.
    Connect To Database    ${DB_MODULE}    ${SOURCE_DB}    alias=${SOURCE_DB_ALIAS}

Connect To Target Database
    [Documentation]    Connect to the target SQLite database.
    Connect To Database    ${DB_MODULE}    ${TARGET_DB}    alias=${TARGET_DB_ALIAS}

Disconnect From All Databases
    [Documentation]    Safely close source and target database connections if open.
    Run Keyword And Ignore Error    Disconnect From Database    ${SOURCE_DB_ALIAS}
    Run Keyword And Ignore Error    Disconnect From Database    ${TARGET_DB_ALIAS}
