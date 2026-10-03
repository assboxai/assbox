# Assbox product contract

Assbox is the dedicated machine on which an owner's agents run, and, when selected, a physical AI terminal.

These documents define accepted **target behavior**. They do not certify that every feature is implemented or qualified. Consult [implementation status](../implementation-status.md) before treating a target as an available operation. Existing operating guides describe the source they accompany.

Start with [strategy](strategy.md), [instance types](instance-types.md), and [architecture](architecture.md). Use [Coder interfaces and external controllers](coder-options.md) to distinguish SSH, relay and private-web routes. Then read [access and security](access-and-security.md), [computer use](computer-use.md), and [lifecycle](lifecycle.md). The [accepted decision](../decisions/0001-product-contract.md) records the invariants. The [dated Linux computer-use matrix](linux-computer-use-support.md) separates browser features, desktop control and exact-build caveats without claiming unrun tests passed. [Dated upstream sources](sources.md) explain external integration facts; the installed package and its test record determine supported behavior.

The six-crate implementation and configuration/publication mechanisms remain documented in [implementation architecture](../architecture.md). Managed-worker operations are specialized instructions, not the definition of every Assbox.
