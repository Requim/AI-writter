SELECT 'CREATE DATABASE novel_research'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'novel_research')\gexec
