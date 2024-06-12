# gitgood
Audit and track your commits with immutable git history.

# Why
Git commit history is not immutable and could be taken advantage of in a supply chain attack. Having immutable commit history that can be compared to a local db can ensure who made certain commits and make auditing easier if supply chain compromise does happen.

# Features
- Checks for conflicts remotely before commiting.
- Stores commit data locally in a sqlite database.
- Commits the data to the Cardano blockchain for immutable commit history.
- Verifies that local commit and onchain commit match.

# Soon
~~- Compare the local commit to the remote commit stored on Cardano.~~
- Allow team members to sync and check commits stored on Cardano.

# Example command

`python3 gitgood.py --project-name awesome-pycardano --git-repo-path ~/awesome-pycardano/ --payment-signing-key-path ../cardano_tests/payment.skey`
