# Independent Desktop credential-storage qualification

Worker enablement leaves credential storage to the selected native Desktop
package. Assbox's native launch policy invokes the pinned client executable and
the graphical session supplies GNOME Secret Service with ordinary first-use
prompts. Check which backend that package actually uses. The optional execution
browser uses disposable profile storage; review its separate
[computer-use contract](../product/computer-use.md).

Chromium documents `basic` as plaintext storage and documents fallback when a selected backend is unavailable. A libsecret flag is therefore neither an encryption guarantee nor proof of unattended startup. An unlocked keyring also does not isolate a secret from every process sharing the Desktop user's authority. [S3](sources.md#s3--chromium-linux-password-storage)

Worker processes must have no filesystem or process access to the controller
Desktop profile. Qualify any credential-backend migration independently of the
worker and plan recovery from a retained profile.

## Backend qualification

Record the effective behavior for each managed launch path when a package or
keyring configuration changes.

Build the resulting controller through the ordinary Assbox transaction. Do not copy a production browser profile or publish credential-bearing logs to demonstrate a migration. Record the Desktop build, keyring service/version, display session and actual selected backend without recording tokens.

Qualify fresh login, reopening the application, controlled reboot, cold unattended boot, network loss/recovery, and the phone's Remote reconnection. Separately test an upgrade of an existing `basic` profile using a dedicated test account; confirm that normal sign-in remains recoverable, whether any reauthentication is required, and how obsolete credential state is treated. Do not infer that old files have been securely erased.

Test keyring-service failure, locked/password-protected keyrings, an unavailable secret service, and the appliance's empty-password/unattended keyring policy. Record fallback or failure explicitly. Never store a keyring-unlock password in Nix, service definitions, source control or an environment file merely to make the test green.

Test rollback of the controller generation and the same persistent Desktop profile. An OS rollback does not roll back application data; retain a protected recovery path. Confirm the backend selected by each qualified launch path. Require a separate approval of these results before adopting that change in the appliance baseline.

Credential migration, old-state retirement and provider session revocation
require deliberate owner action.
