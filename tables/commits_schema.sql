CREATE TABLE commits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    onchain_id TEXT NOT NULL,
    project_name TEXT NOT NULL,
    local_commit_hash TEXT NOT NULL,
    commit_message TEXT NOT NULL,
    commit_timestamp TEXT NOT NULL
);
