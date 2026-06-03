-- Run this as a superuser ONCE
-- Replace 'YOUR_DB_NAME' with your actual database name

CREATE USER nl_agent_ro WITH PASSWORD 'change_me_in_env';
GRANT CONNECT ON DATABASE YOUR_DB_NAME TO nl_agent_ro;
GRANT USAGE ON SCHEMA public TO nl_agent_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO nl_agent_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT ON TABLES TO nl_agent_ro;
