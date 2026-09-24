# Scoped Git credentials and staging repositories

This is Assbox's recommended worker workflow, not a requirement to use GitHub. Other forges can use equivalent restricted credentials and separate promotion authority.

## The intended boundary

Keep a dedicated credential inside the execution worker. Grant it only the access needed to read and push selected agent/staging repositories. Keep trusted-upstream write authority on another trusted workstation or service. Do not add upstream synchronization credentials to the Assbox controller: its purpose is to control the worker, not administer source repositories.

Assume every selected agent in the worker can obtain and use this credential. A credential helper, mode 0600 and hidden input improve hygiene; they do not isolate a token from a compromised worker. A token's repository allowlist limits its authority, not the destinations to which an agent can transmit readable source or other worker secrets.

## Prepare staging repositories from the trusted side

Create repositories for agent work without production deployments, package-publication authority, organization secrets or privileged CI runners. Seed only the source and history you intend to expose to agents and model providers. Audit history as well as the current tree for secrets. Use separate names/remotes so the review boundary remains obvious.

**Prefer independently permissioned staging repositories when you need a strong administrative separation.** A GitHub-native fork can be appropriate, but review its repository-network behavior first: visibility and some permissions are inherited/shared, and Git objects may be accessible within the network. A fork is not a private quarantine vault [G1]. “Internal” is also a GitHub visibility category; do not assume it means visible only to this agent.

The trusted side synchronizes approved upstream revisions into staging. The worker clones and pushes staging only. Public upstream source may still be readable anonymously; the security requirement is that the worker has no privileged upstream access, especially no write authority. Private upstream synchronization belongs outside the worker.

## Create a fine-grained PAT

Using a trusted browser on another trusted device for GitHub administration, create a fine-grained GitHub PAT for the intended resource owner and **only the selected staging repositories**. Start with repository Contents read/write for normal source work; add other permissions only for an explicitly reviewed task. Fine-grained PATs have owner/repository/permission controls, expiration and possible organization approval requirements; they also have documented limitations for some collaboration scenarios [G2]. Do not replace them with a broad classic token merely to make a denied operation pass.

Do not grant Administration, Actions management, Secrets, deployment or workflow-changing permissions by default. A rejected workflow-file push is a reason to use trusted review/promotion, not automatically expand the agent's authority. Choose an expiration and maintain a revocation/renewal procedure. A task stopped by expiration must report authentication failure, not fall back to another controller credential.

One PAT may suit several approved repositories under one owner. Different owners or risk categories can need separate restricted credentials. Keep their selection and permissions documented outside the worker. An allowlisted repository may itself have dangerous integrations: token scope alone is not the full risk assessment.

## Enroll the credential inside the worker

Open a worker shell from the trusted controller account:

```sh
assbox worker shell
```

Then, inside the worker:

```sh
hostname
cat /etc/assbox/worker-role
mkdir -p ~/projects
cd ~/projects
git clone https://github.com/AGENT-OWNER/PROJECT-STAGING.git
```

Replace the example repository with an explicitly approved one. Use Git's credential prompt/your reviewed worker-side credential helper to enter the token, never a token-bearing URL. Do not paste tokens into chat, command arguments, shell history, environment declarations in Nix, a project file, the controller keyring or a diagnostic report. Do not forward the controller SSH agent, controller `gh` state or browser cookies.

Credential helpers are a choice, not an Assbox requirement. A memory cache expires/requires login again; a persistent worker helper stores sensitive material in the worker compromise domain. Check the helper actually selected by `git config --show-origin --get-all credential.helper`, especially when using multiple owners. Never “fix” authentication by installing your normal personal SSH private key in the worker. Assbox does not currently provide a PAT collection or GitHub account-management command.

After login, verify origin URLs contain no token. Confirm clone and a disposable branch push succeed on an allowed staging repository. Confirm unrelated private repositories and upstream write operations remain unauthorized, using a non-destructive check that does not expose credentials in logs. Test effective permissions, not just the token's name. If a test could publish or overwrite something important, perform it in a disposable authorization fixture instead.

## Repository automation is another execution boundary

Disable Actions and other automatic integrations in staging until explicitly reviewed. Do not expose production secrets, cloud identities, publishing credentials, privileged/self-hosted runners or release approvals to code writable by the worker. Inspect copied workflow files before enabling automation.

Where CI is necessary, run it as disposable, least-privileged untrusted-code execution. GitHub warns that untrusted input/code and privileged workflow contexts can expose credentials; self-hosted runner and `pull_request_target` workflows need particular care [G3]. A token that cannot read secrets through the API can still write code later executed by an overly privileged integration. “No Secrets permission on the PAT” is not proof that CI secrets are unreachable.

The trusted promotion pipeline must not automatically execute staged hooks, build scripts, instructions, deployment manifests or workflows with upstream privileges. Review changes to those files explicitly. Use isolated tests before promotion; simply opening/running the repository on a trusted personal machine can cross the boundary.

## Daily workflow

Work in branches in the worker, push to staging, review from the trusted side, then promote selected changes upstream. Promote deliberately through a reviewed PR, cherry-pick or equivalent process; Assbox does not automate an upstream merge. Independent agent reviews can be useful but do not replace human authority or security review.

Ordinary SSH transport remains available for explicit file movement:

```sh
ssh assbox-worker
scp ./task-input.txt assbox-worker:projects/
rsync -a --safe-links ./project-input/ assbox-worker:projects/project-input/
```

Run these as the controller account after installing its managed alias. Do not transfer a whole home, hidden credential directory or unreviewed secret-bearing `.git/config`. File transfer intentionally moves selected bytes; it is not a bidirectional live filesystem mount. Prefer Git for canonical source synchronization. Do not run hooks from returned content on the trusted controller.

## Compromise and recovery

Stop the worker through `sudo assbox worker stop`, which also suspends health/retry startup. Revoke exposed PATs and provider credentials from trusted interfaces; deleting local files or reverting the worker OS does not revoke already-stolen credentials. Treat staging commits and integrations as suspect. Rebuild/inspect staging from a trusted source as necessary.

Follow the [operations recovery procedure](operations.md) for a fresh worker state disk. Never mount an attacker-controlled filesystem on the controller to “clean it up.” The root overlay is disposable but `/home` survives routine restarts, so restarting is not a reset. Re-enroll fresh credentials in the clean worker and clone reviewed source. Document what was revoked and restored without copying tokens into the incident record.

## References

Checked September 24, 2026. The recommended staging/promotion pattern is Assbox's design, not a GitHub security guarantee.

- [G1 — GitHub fork networks, permissions and visibility](https://docs.github.com/en/pull-requests/reference/forks)
- [G2 — Fine-grained personal access tokens](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens)
- [G3 — Secure use of GitHub Actions](https://docs.github.com/en/actions/reference/security/secure-use)
