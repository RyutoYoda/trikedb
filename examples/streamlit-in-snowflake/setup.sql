-- Everything this sample needs on the Snowflake side, in the order it has
-- to be created. Run it once as a role that can create policies and
-- integrations (ACCOUNTADMIN, or a role with CREATE INTEGRATION plus the
-- masking/row-access privileges), then hand the objects to the role the
-- app runs as.
--
-- Names to change are all in the first block. They match the constants at
-- the top of `curation.py`, `graph_store.py` and `snowflake.yml` -- if you
-- change one here, change it there too.

SET APP_DB    = 'DEMO_DB';
SET APP_SCHEMA = 'KG';
SET APP_ROLE  = 'KG_CURATOR';       -- the role people hold when they use the app

CREATE DATABASE IF NOT EXISTS DEMO_DB;
CREATE SCHEMA   IF NOT EXISTS DEMO_DB.KG;

USE SCHEMA DEMO_DB.KG;


-- ---------------------------------------------------------------- the graphs
--
-- One row per graph file. The YAML in git is the source of truth; these
-- rows are a derived copy that your pipeline (CI, a task, a script --
-- whatever you already run) pushes in after a merge. `graph_store.py`
-- reads them and never writes them.
--
-- The name is `<prefix>/<graph>` so one table can hold several graphs, and
-- so `graph_store.graph_names()` can discover the list instead of having
-- it hardcoded somewhere that rots.

CREATE TABLE IF NOT EXISTS TRIKE_GRAPHS (
  NAME        STRING       NOT NULL,   -- e.g. 'demo/dbt'
  CONTENT     STRING       NOT NULL,   -- the YAML, verbatim
  UPDATED_AT  TIMESTAMP_LTZ DEFAULT CURRENT_TIMESTAMP(),
  CONSTRAINT PK_TRIKE_GRAPHS PRIMARY KEY (NAME)
);


-- --------------------------------------------------------------- the outbox
--
-- One row per proposal. The screen writes rows here; `outbox/` drains them
-- into a pull request. STATUS is the whole state machine:
--
--     pending   written by the screen, not carried yet
--     queued    carried into PR_URL
--     refused   the guard rejected it; ERROR says why
--
-- There is deliberately no "applied" state. Whether a proposal became a
-- fact is decided by the PR being merged, which happens in git, not here.

CREATE TABLE IF NOT EXISTS KG_OUTBOX (
  ID           STRING       DEFAULT UUID_STRING(),
  AUTHOR       STRING       NOT NULL,   -- the Snowflake user who proposed it
  TARGET_YAML  STRING       NOT NULL,   -- e.g. 'dbt.yaml'
  OP           STRING       NOT NULL,   -- add_triple / set_node / declare_link
  PAYLOAD      VARIANT      NOT NULL,   -- the arguments for that op
  NOTE         STRING       NOT NULL,   -- why this is being proposed
  PROV         STRING       NOT NULL,   -- where it came from
  STATUS       STRING       DEFAULT 'pending',
  PR_URL       STRING,
  ERROR        STRING,
  CREATED_AT   TIMESTAMP_LTZ DEFAULT CURRENT_TIMESTAMP(),
  PROCESSED_AT TIMESTAMP_LTZ,
  CONSTRAINT PK_KG_OUTBOX PRIMARY KEY (ID)
);


-- ------------------------------------------------------------- the credentials
--
-- One row per person: their own GitHub personal access token, so that the
-- PR is opened as them. No shared token, no shared bot account -- the
-- commits carry the name of whoever pressed the button.
--
-- LAST4 exists so the screen can show "the one ending 1a2b" without ever
-- reading TOKEN back. LAST_ERROR is where an expired or under-scoped token
-- becomes visible to its owner: GitHub answers 401/403 and that string is
-- stored here. There is no expiry column on purpose -- a date typed into a
-- form is self-reported and drifts from the real one, and filtering on the
-- drifted value produces "valid on GitHub, unusable from the screen" with
-- the reason visible nowhere.

CREATE TABLE IF NOT EXISTS KG_OUTBOX_TOKEN (
  SF_USER      STRING       NOT NULL,   -- CURRENT_USER() of the owner
  TOKEN        STRING       NOT NULL,   -- masked; see the policy below
  GH_LOGIN     STRING,
  LAST4        STRING,
  CREATED_AT   TIMESTAMP_LTZ DEFAULT CURRENT_TIMESTAMP(),
  LAST_USED_AT TIMESTAMP_LTZ,
  LAST_ERROR   STRING,
  CONSTRAINT PK_KG_OUTBOX_TOKEN PRIMARY KEY (SF_USER)
);


-- ------------------------------------------------------- who may see a token
--
-- Two policies, both testing `CURRENT_USER() = SF_USER`:
--
--     rows    only your own row is visible at all
--     column  TOKEN reads back as '***' to anyone else
--
-- Two layers rather than one because they fail differently. The row policy
-- hides the row; the masking policy means that if a row is ever exposed by
-- some other path -- a view, a share, a future grant -- the value still
-- does not come out.
--
-- **A policy expression is evaluated with the real user name, even inside
-- a Streamlit in Snowflake app.** This is worth stating because it reads
-- backwards: `SELECT CURRENT_USER()` *issued by* the app returns NULL, but
-- `CURRENT_USER()` *inside a policy expression* is the real name, and
-- QUERY_HISTORY records that same real name. So `CURRENT_USER()` cannot
-- tell you "inside the app" from "in a worksheet", and rewriting these to
-- `CURRENT_USER() IS NULL` breaks them -- that is not true inside the app
-- either.
--
-- The trap the app has to avoid is on the Python side: if the app stores
-- rows under `str(CURRENT_USER())`, the name is the string 'None' and
-- `CURRENT_USER() = 'None'` is never true. A row access policy does not
-- restrict INSERT, so registration keeps succeeding and produces a row
-- nobody can read. `curation.current_user()` takes the name from
-- `st.user` for exactly this reason.

CREATE MASKING POLICY IF NOT EXISTS KG_OUTBOX_TOKEN_MASK AS (val STRING)
  RETURNS STRING ->
    CASE WHEN CURRENT_USER() = SF_USER THEN val ELSE '***' END;

CREATE ROW ACCESS POLICY IF NOT EXISTS KG_OUTBOX_TOKEN_ROWS AS (sf_user STRING)
  RETURNS BOOLEAN ->
    CURRENT_USER() = sf_user;

ALTER TABLE KG_OUTBOX_TOKEN
  MODIFY COLUMN TOKEN SET MASKING POLICY KG_OUTBOX_TOKEN_MASK;

ALTER TABLE KG_OUTBOX_TOKEN
  ADD ROW ACCESS POLICY KG_OUTBOX_TOKEN_ROWS ON (SF_USER);


-- ------------------------------------------------------------ the one way out
--
-- A Streamlit in Snowflake app cannot reach the internet unless you open a
-- hole, and the hole is exactly one host. Opening `api.github.com:443` is
-- what lets the app open a pull request; it can reach nothing else.
--
-- If you skip this, everything else still works -- proposals are written,
-- the guard runs, the screen looks healthy -- and pressing "open a PR"
-- fails at the last step.

CREATE OR REPLACE NETWORK RULE GITHUB_NETWORK_RULE
  MODE = EGRESS
  TYPE = HOST_PORT
  VALUE_LIST = ('api.github.com:443');

CREATE OR REPLACE EXTERNAL ACCESS INTEGRATION GITHUB_ACCESS_INTEGRATION
  ALLOWED_NETWORK_RULES = (DEMO_DB.KG.GITHUB_NETWORK_RULE)
  ENABLED = TRUE;

-- The integration has to be attached to the app itself. `snowflake.yml`
-- does not carry it, so it is one statement after the first deploy (the
-- app object must exist first):
--
--     ALTER STREAMLIT DEMO_DB.KG.GRAPH_CURATION
--       SET EXTERNAL_ACCESS_INTEGRATIONS = (GITHUB_ACCESS_INTEGRATION);


-- -------------------------------------------------------------------- grants
--
-- No grant on TOKEN beyond what the policies allow. People can write their
-- own row and read their own row; that is the entire permission model for
-- credentials, and it is enforced by SQL rather than by the app.

GRANT USAGE ON DATABASE DEMO_DB              TO ROLE IDENTIFIER($APP_ROLE);
GRANT USAGE ON SCHEMA   DEMO_DB.KG           TO ROLE IDENTIFIER($APP_ROLE);
GRANT SELECT ON TABLE   DEMO_DB.KG.TRIKE_GRAPHS TO ROLE IDENTIFIER($APP_ROLE);
GRANT SELECT, INSERT, UPDATE ON TABLE DEMO_DB.KG.KG_OUTBOX
  TO ROLE IDENTIFIER($APP_ROLE);
GRANT SELECT, INSERT, DELETE, UPDATE ON TABLE DEMO_DB.KG.KG_OUTBOX_TOKEN
  TO ROLE IDENTIFIER($APP_ROLE);
GRANT USAGE ON INTEGRATION GITHUB_ACCESS_INTEGRATION
  TO ROLE IDENTIFIER($APP_ROLE);
