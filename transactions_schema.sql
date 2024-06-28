CREATE TABLE transactions (
    transaction_hash TEXT NOT NULL,
    transaction_id INTEGER,
    FOREIGN KEY(transaction_id) REFERENCES commits(id)
);
