# Document Metadata

| Field | Value |
|---|---|
| Document | `GOVERNANCE.md` |
| Title | Repository Governance and Constitutional Authority |
| Authority Level | Level 2 — Repository Governance |
| Version | 1.0.0 |
| Status | Ratified |
| Purpose | Define document authority, ownership, versioning, amendment, and conflict resolution. |
| Higher Authority | [`MANIFESTO.md`](MANIFESTO.md) |
| Governed Documents | All documents below Level 1 and the process used to amend constitutional documents. |
| Related Documents | [`AGENT.md`](AGENT.md), [`ANTI_GOALS.md`](ANTI_GOALS.md), [`README.md`](README.md) |

# Repository Governance

## Authority hierarchy

1. **Level 1 — Constitution:** [`MANIFESTO.md`](MANIFESTO.md) defines why the platform exists and its immutable product philosophy.
2. **Level 2 — Constitutional governance:** this document defines authority and amendment; [`AGENT.md`](AGENT.md) governs AI contributors; [`ANTI_GOALS.md`](ANTI_GOALS.md) makes constitutional exclusions operational. These documents have equal authority within their separate subjects.
3. **Level 3 — Architecture and doctrine:** approved system, domain, data, security, and decision-intelligence architecture documents apply constitutional principles to a subsystem.
4. **Level 4 — Contracts and specifications:** schemas, interface contracts, feature specifications, migration plans, and acceptance criteria govern bounded implementations.
5. **Level 5 — Operational records:** implementation reports, audits, test reports, runbooks, and decision records describe work or evidence.
6. **Level 6 — Introduction and guidance:** [`README.md`](README.md), tutorials, examples, and explanatory notes help readers navigate but create no higher authority.

Code and tests must conform to governing documents. They are evidence of current behavior, not authority to silently revise product philosophy.

## Resolving conflicts

The higher-authority document prevails. At the same level, the document with the narrower declared purpose governs its subject. If same-level documents cannot be reconciled, implementation pauses until their owners record a resolution or amend them together.

Recency alone does not override authority. A pull request, issue, prompt, comment, test, or existing behavior cannot amend a governing document implicitly. Conflicts must be surfaced, never averaged or resolved through convenient interpretation.

## Ownership

Product owners own the Constitution and approve constitutional amendments. Maintainers own Level 2 documents and ensure lower-level documents identify their authority. Subsystem owners maintain Level 3 and Level 4 documents. Authors of operational records own their accuracy, evidence, date, and scope.

Ownership grants stewardship, not permission to contradict higher authority.

## Versioning

Constitutional documents use semantic versions:

- **PATCH** clarifies wording without changing meaning.
- **MINOR** adds guidance consistent with the existing philosophy.
- **MAJOR** changes a product boundary, pillar, authority rule, or anti-goal.

The version changes in the same review as the substance. Related constitutional documents must be checked for consistent terminology and links. History remains available through version control.

## Constitutional amendments

An amendment is explicit and exceptional. Its proposal must state:

1. the principle or boundary being changed;
2. why the current Constitution no longer serves the mission;
3. the affected pillars, anti-goals, architecture, contracts, and users;
4. risks to human judgment and evidence authority;
5. coordinated document changes and new versions.

A product owner must approve the amendment through a dedicated review. Dependent implementation begins only after ratification. Emergency code may protect users or data, but it does not amend the Constitution.

## Adding future documents

Every governing or architectural document must declare: Document, Title, Authority Level, Version, Status, Purpose, Higher Authority, Governed Documents, and Related Documents.

Assign the lowest authority sufficient for the purpose, name the direct higher authority, avoid restating higher-level doctrine, and link related documents. New documents refine an existing principle; they do not acquire authority merely by declaring it.

Changes to [`AGENT.md`](AGENT.md) or [`ANTI_GOALS.md`](ANTI_GOALS.md) must be checked against [`MANIFESTO.md`](MANIFESTO.md). Changes to this governance process require constitutional review because governance determines how later conflicts are settled.
