# Independent Desktop credential-storage qualification

Worker isolation does not change the Desktop credential-storage backend. The main source retains the appliance's `--password-store=basic` argument. A change to libsecret is deferred and no optional backend patch is shipped in this tranche.

Chromium documents `basic` as plaintext storage and documents fallback when a selected backend is unavailable. A libsecret flag is therefore neither an encryption guarantee nor proof of unattended startup. An unlocked keyring also does not isolate a secret from every process sharing the Desktop user's authority. [S3](sources.md#s3--chromium-linux-password-storage)

The worker boundary is different: worker processes must not obtain filesystem/process access to the controller Desktop profile at all. Keeping an existing login backend avoids making VM deployment depend on an unqualified credential migration. It does not endorse plaintext storage as protection against stolen disks or a compromised controller.

## Future backend qualification

If a later change adopts libsecret, update both launcher paths together and test it separately from worker integration.

Build the resulting controller through the ordinary Assbox transaction. Do not copy a production browser profile or publish credential-bearing logs to demonstrate a migration. Record the Desktop build, keyring service/version, display session and actual selected backend without recording tokens.

Qualify fresh login, reopening the application, controlled reboot, cold unattended boot, network loss/recovery, and the phone's Remote reconnection. Separately test an upgrade of an existing `basic` profile using a dedicated test account; confirm that normal sign-in remains recoverable, whether any reauthentication is required, and how obsolete credential state is treated. Do not infer that old files have been securely erased.

Test keyring-service failure, locked/password-protected keyrings, an unavailable secret service, and the appliance's empty-password/unattended keyring policy. Record fallback or failure explicitly. Never store a keyring-unlock password in Nix, service definitions, source control or an environment file merely to make the test green.

Test rollback of the controller generation and the same persistent Desktop profile. An OS rollback does not roll back application data; retain a protected recovery path. Confirm that both launcher paths request the intended backend. Require a separate approval of these results before adopting that change in the appliance baseline.

No credential migration, deletion, keyring password change, provider session revocation or migration acceptance is performed by this source package.
