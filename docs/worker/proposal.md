# Managed-worker reference

The product-wide architectural authority is [Assbox product architecture](../product/architecture.md), with decisions in the [product contract ADR](../decisions/0001-product-contract.md). The worker is a specialized execution boundary for sensitive local controllers, not the default shape of every Assbox.

For the implementation, read [controller model](controller-model.md), [lifecycle](lifecycle.md), [operations](operations.md), [security](security.md) and [client routing](client-routing.md). For observed source and qualification status, read [global implementation status](../implementation-status.md) and [worker implementation status](implementation-status.md).

Claude SSH Code, local Cowork provider virtualization and cloud tasks must not be collapsed into one worker route. Optional headless computer use stays in the execution domain, never implicitly on the protected physical controller display. Configuration/operations examples apply to the source version they accompany; target additions require implementation and acceptance.
