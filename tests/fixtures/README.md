# Disposable acceptance fixtures

`release_transport.py` supplies deterministic download and verified-certificate
observations to a separately compiled Rust test executable. It does not perform
cryptography. The authenticated-release VM separately executes the pinned real
GitHub CLI against genuine signatures from that CLI's pinned upstream test data.
These layers do not establish that an Assbox release exists on GitHub or that its
repository environment has been provisioned correctly.
