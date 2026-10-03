# Qualification records

`acceptance.json` is the complete 116-requirement contract from the supplied implementation plan. Every entry is initially `not_run` with null evidence. `work-items.json` preserves the 23 engineering packages. `linux-computer-use.json` is dated upstream evidence, not a permanent capability resolver or an Assbox pass.

For each actual run, record source commit and lock SHA256, controller/guest OS and architecture, hardware and hypervisor, exact package/client/helper versions, account and entitlement scope without credentials, authentication mode, commands, UTC date, observed result and redacted evidence. Distinguish package/CLI checks, integration sessions, optional capabilities and native policy enforcement. Conditional `not_applicable` needs its account/build/selection reason.

Run the existing release gates only when full testing is authorized. Native GUI, auth, networking and hardware checks must use disposable environments and scoped credentials. Mac external Desktop SSH, phone→Mac→SSH, Linux native→managed worker, and experimental direct Codex relay need independent records. Happier's pinned dry-run/service-path oracle is in `scripts/providers/happier_contract.py`; it inspects behavior without installing a vendor service.

A native contract belongs in immutable Nix configuration. Its qualification JSON must bind `app`, `contract`, exact `client` store executable, `platform`, `accountScopeDigest`, and `status: passed`. Its bounded probe receives `ASSBOX_NATIVE_REQUEST` and returns the same scope plus `policyRequestDigest`, `effectivePolicyDigest` and the complete surface map defined in `scripts/native/policy.py`. It must inspect/apply effective controls for the exact installed build, account and helpers. A fixture that returns expected answers is not a qualified probe. Receipt freshness is at most 45 seconds by default; a supervised client closes when observations expire or conflict. Account/workspace/helper changes must be part of the probe's effective scope.

No generic Linux policy probe is presented as enforceable. If the selected app/account cannot establish the strict policy, leave the native client inactive and choose a separately explicit qualified route or web instance.

[candidate-checks.json](candidate-checks.json) is the separately scoped lightweight check record. Its results do not mark native, provider, hardware or release acceptance as passed.

[source-audit.json](source-audit.json) records source traceability for all 23 work
packages and 116 acceptance requirements at its named commit. Each mechanism
identifies behavior, source, qualification paths and remaining limits. A covered
row means the candidate contains an implementation or explicit contract gate;
it does not mean the requirement passed. W21/W22 execution remains deferred at
the owner's request. The original planning work ledger is preserved separately.

The [external Coder fixture](../docs/external-coder-fixture.md) records separate
Mac/guest canaries and initial/disconnected/reconnected tasks. Its result is
limited to those observed paths; it deliberately does not promote a route to
qualified. The optional browser/display substrate gate is `computer-use-vm`.
Neither native fixture has been run in this lightweight candidate pass.
