<!-- doc-status: dated -->

# AWS IAM from zero

- Date: 2026-07-20
- Audience: someone comfortable with code but not with AWS's identity system.
- Purpose: a reusable foundation for the infrastructure explainers in this
  directory. Read it once; other explainers link back to it instead of
  re-explaining these terms.

This primer builds up, one concept at a time, to the four ideas the
[deployer permissions boundary explainer](deployer-permissions-boundary.md)
depends on: **roles**, **the Allow/Deny evaluation model**, **instance profiles
plus instance metadata**, and **permissions boundaries**. Everything before those
is scaffolding to make them make sense.

---

## 1. The account

An **AWS account** is the top-level container. It owns cloud resources — virtual
machines, networks, storage buckets, databases — and it owns the *identities*
allowed to act on those resources. An account is identified by a 12-digit number
(this project's is `675789572470`). A useful mental model: the account is a
building, resources are the rooms and equipment inside it, and everything in the
rest of this primer is about **who is allowed to open which doors**.

Two properties of AWS accounts matter throughout:

- **Everything is denied by default.** A brand-new identity in an account can do
  *nothing*. Every capability has to be granted explicitly. There is no "admin
  by default" — even the ability to list what exists must be handed out.
- **The account is a blast-radius boundary.** Actions in one account generally
  can't reach another account's resources unless someone deliberately sets up
  cross-account trust. This is why "dedicated, disposable account" is itself a
  security measure: the worst case is scoped to that one account.

---

## 2. Identities: users and roles

An **identity** (AWS calls these "principals") is a thing that can be
authenticated and can then attempt actions. There are two kinds worth knowing:

- An **IAM user** is a long-lived identity with permanent credentials (a password,
  or an access-key pair). It usually represents a human or a legacy script. Users
  are the *old* way and this project deliberately avoids them for automation —
  permanent credentials are exactly the thing that leaks.
- An **IAM role** is an identity **with no permanent credentials**. Nobody "is"
  a role. Instead, an approved principal *assumes* the role for a short time and,
  while assuming it, receives temporary credentials that expire (typically in an
  hour). Think of a role as a **costume with a keycard sewn into it**: whoever is
  allowed to put it on can, for a while, open exactly the doors that keycard
  opens — and crucially, *while wearing the costume, their own everyday identity
  stops mattering.* They have precisely the role's powers, no more and no less.

Roles are the backbone of automated AWS access, and of this project. When the
CI/CD pipeline needs to build the demo, it doesn't hold a password — it assumes a
role, does its work with the temporary credentials, and the credentials expire.
Nothing long-lived to steal.

Every role has **two** separate policies attached, and confusing them is the most
common early mistake:

1. A **trust policy** (a.k.a. the *assume-role* policy) — answers **"who is
   allowed to put on this costume?"** It names the principals permitted to
   assume the role.
2. One or more **permission policies** — answer **"what can the wearer do once
   they've put it on?"** These list the actual capabilities.

A role with a generous permission policy but a tight trust policy is safe:
powerful, but almost nobody can wear it. Keep these two questions separate as you
read anything about IAM.

---

## 3. ARNs: how AWS names things

An **ARN** (Amazon Resource Name) is the globally unique identifier for any AWS
thing. They read left to right as increasingly specific:

```
arn:aws:iam::675789572470:role/annotated-maps-deployer
└┬┘ └┬┘ └┬┘  └────┬─────┘ └──────────┬───────────────┘
 │   │   │        │                   └ the resource: a role with this name
 │   │   │        └ the account number
 │   │   └ the service (iam)
 │   └ the partition (standard AWS)
 └ literally the string "arn"
```

Two things about ARNs matter later:

- **Wildcards.** A policy can target `role/annotated-maps-*` to mean "every role
  whose name starts with `annotated-maps-`." This is how a policy fences itself
  to a namespace of resources.
- **ARNs are how a policy says "this exact thing and nothing else."** When a
  security rule needs to apply to one specific role — not roles that merely look
  like it — it references that role's ARN. (You will see later why referencing an
  ARN *by name literal* versus *by a live reference* is a real correctness
  concern.)

---

## 4. Policies: the Allow/Deny model

A **policy** is a JSON document listing **statements**. Each statement has, at
minimum:

- an **Effect**: either `Allow` or `Deny`
- a set of **Action**s: e.g. `iam:CreateRole`, `ec2:RunInstances`,
  `s3:GetObject` — always `service:Operation`
- a set of **Resource**s: the ARNs the statement applies to (or `*` for "any")
- optionally, **Condition**s: extra tests that must hold for the statement to
  apply (more in §5)

### The evaluation rule (memorize this)

When a principal attempts an action, AWS collects every applicable statement from
every relevant policy and decides using a fixed three-step rule:

1. **Is there an explicit `Deny` that matches?** If yes → **denied.** Stop. A Deny
   always wins; nothing can override it.
2. **Otherwise, is there an `Allow` that matches?** If yes → **allowed.**
3. **Otherwise** → **denied** (the default-deny from §1).

Two consequences fall out of this and both are load-bearing later:

- **A `Deny` beats any `Allow`, always.** You cannot out-allow a Deny. This is
  what makes a Deny a genuine wall rather than a preference.
- **You cannot carve an exception out of a Deny with an Allow.** If a Deny
  matches `iam:*`, you *cannot* add `Allow iam:GetRole` to let one read through —
  the Deny still wins. The only way to let `GetRole` through is to make the Deny
  itself narrower (list the specific mutating actions instead of `iam:*`). This
  exact subtlety caused a real, documented failure in this project — keep it in
  mind.

### Identity policies vs. resource policies

The policies in §2 are **identity-based** — attached to the principal, describing
what *it* can do. Some resources (S3 buckets, SNS topics, and importantly a
role's *trust* policy) also carry **resource-based** policies describing who may
act *on them*. For this primer, the trust policy from §2 is the resource-based
policy that matters: it lives on the role and says who may assume it.

---

## 5. Conditions: policies that depend on context

A **Condition** narrows a statement so it applies only when some contextual key
matches. For example, "allow this, but only if the request is tagged a certain
way," or "only if the target carries a specific attribute." Conditions are
written as an operator plus a key plus expected values, e.g.
`StringEquals { "iam:PermissionsBoundary": "<some ARN>" }`.

Two operator behaviors matter later:

- **`StringEquals`** passes only when the key is present *and* equals the value.
- **`StringNotEquals`** passes when the key differs — **and also when the key is
  absent entirely.** A missing key is "not equal." This is the mechanism that
  lets a rule say "deny this action unless the request explicitly carries the
  right value" — because a request that omits the value trips the
  `StringNotEquals` and gets caught by the Deny. This is precisely how a
  permissions boundary is *forced* onto every newly created role (§10).

---

## 6. Assuming a role (STS)

The act of putting on the costume is a call to **STS** (Security Token Service):
`sts:AssumeRole` (or a federated variant). If the caller is permitted by the
role's *trust* policy, STS hands back a set of **temporary credentials** scoped to
that role. From that moment until they expire, calls made with those credentials
are evaluated against the role's *permission* policies — the caller's original
identity no longer factors in.

This is worth restating because it drives the whole escalation story later: **once
you assume a role, you have that role's powers, evaluated as that role — as a
distinct principal from whoever you were a moment ago.** If role B is more
powerful than role A, and role A is allowed to create and assume role B, then role
A has effectively laundered itself into more power *by becoming a different
principal.* Hold that thought.

---

## 7. Roles for machines: instance profiles and instance metadata

A virtual machine (an **EC2 instance**) often needs AWS permissions of its own —
to read a bucket, write logs, and so on. It gets them by wearing a role, but
there's a wrapper in the way:

- An **instance profile** is a thin container around a single role that exists
  solely so an EC2 instance can wear it. You create the role, create the instance
  profile, put the role in the profile, and launch the instance *with* that
  profile. (In most tooling this is one conceptual step, but the underlying API
  has the separate pieces — they show up individually in the escalation story.)
- Once running, the instance can ask a special link-local address —
  **`169.254.169.254`, the instance metadata service** — "what are my current
  credentials?" The metadata service hands back live temporary credentials for the
  role the instance is wearing.

Here is the sharp edge: **anything that can run code on that instance can read
those credentials off the metadata service.** So "attach a powerful role to an
instance, then read its metadata" is a completely ordinary, fully-supported way to
*obtain that role's credentials as a string you can use from anywhere.* It's not
an exploit — it's how instances are meant to get their credentials. It becomes a
problem only when combined with the ability to attach an *over-powerful* role,
which is the next concept.

---

## 8. `PassRole`: the guard on "give a role to a service"

Because attaching a role to an instance hands that instance the role's power,
AWS gates it behind a distinct permission: **`iam:PassRole`.** To launch an EC2
instance wearing role X, you need permission to *pass* role X to EC2. `PassRole`
is the checkpoint that's supposed to stop a weak principal from handing a strong
role to a machine it controls. If a principal can `PassRole` a powerful role and
`ec2:RunInstances` with it, §7's metadata trick converts directly into "hold that
powerful role's credentials." Watch for `PassRole` and `RunInstances` appearing
together — that pair is a privilege-escalation primitive.

---

## 9. Service-linked roles: AWS's own helper identities

Some AWS services need to act on your behalf in the background (EKS managing node
groups, load balancing managing network interfaces). They use **service-linked
roles** (SLRs) — special roles AWS creates and controls, living under a reserved
ARN path `role/aws-service-role/...`. The action to make one is
**`iam:CreateServiceLinkedRole`**, and — importantly — it is a *different action*
from the ordinary `iam:CreateRole`. That distinction matters when a security rule
wants to block ordinary role creation *without* breaking the legitimate,
unavoidable creation of service-linked roles: the rule targets `iam:CreateRole`
and leaves `iam:CreateServiceLinkedRole` alone. (This project also learned the
hard way that a service will sometimes *read* an SLR — `iam:GetRole` — to check
whether it exists before creating it, so blocking the read breaks the create.)

---

## 10. Permissions boundaries: a ceiling, not a grant

This is the concept the whole boundary explainer turns on, so it gets the most
space.

Normally a role's power is the union of its permission policies — add a policy,
gain its powers. A **permissions boundary** works the opposite way: it is a policy
attached to a role that acts as a **ceiling on what that role can *effectively*
do**, no matter what its permission policies say. The effective permissions of a
boundary-capped role are the **intersection**:

```
effective power  =  (what the role's permission policies allow)
                    ∩  (what the boundary allows)
```

Concretely: if a role's permission policy grants `AdministratorAccess` (allow
everything), but its boundary only allows `s3:GetObject`, then the role can do
exactly one thing — `s3:GetObject`. The admin grant is *present but capped*. The
boundary is a lid the role cannot lift from the inside; it can only ever reach the
smaller of its two policies at any given action.

Two facts make boundaries a *containment* tool rather than a mere convenience:

- **A boundary caps a role even against its own future grants.** Attaching a
  bigger policy later doesn't help — the intersection with the boundary is still
  the ceiling.
- **You can force new roles to carry a boundary.** Using the `StringNotEquals` /
  absent-key trick from §5, a policy can say: *"Deny `iam:CreateRole` unless the
  request sets a permissions boundary equal to this specific ARN."* Now any role
  this principal creates is *born* under the boundary — it cannot mint an
  uncapped role at all. Combined with capping the *grant* actions
  (`AttachRolePolicy`, `PutRolePolicy`) the same way, this closes the "create a
  more-powerful role and launder into it" escalation from §6: the newly created
  role's admin grant is neutered by the boundary ceiling.

That is the entire strategy of the boundary design in this repo. Everything in
that explainer is either (a) writing the boundary's Allow-set so it's a *useful*
ceiling — high enough that the legitimate roles still work, low enough that
laundering buys nothing — or (b) plugging the specific ways a clever principal
could dodge the "must carry the boundary" rule.

---

## 11. OIDC federation: the door from outside AWS

One loose end: how does something *outside* AWS — a GitHub Actions run, say —
assume a role without a permanent AWS credential? Through **OIDC federation.**
AWS is told to trust an external identity provider (GitHub's, in this project).
When a GitHub workflow runs, GitHub mints a short-lived signed token describing
*which repository, which environment, which trigger*. The role's trust policy
(§2) says, in effect, "allow assumption by GitHub's OIDC provider, but only when
the token's `sub` claim says it came from *this exact repo and environment*."

The upshot for the boundary story: the **only door** into this project's AWS
account is a GitHub workflow of the right shape assuming the deployer role. That
door is narrow (a fork can't forge the token), which is why the escalation the
boundary closes is about *what someone already through the door can do*, not about
widening who can get in. The trust-policy details and their fork-safety are
argued in
[ADR-0010](../../adr/0010-pipeline-apply-role.md); this primer only needs you to
know the door exists and is OIDC-shaped.

---

## Glossary (quick reference)

| Term | One-line meaning |
|---|---|
| Account | Top-level container for AWS resources and identities; a blast-radius boundary. |
| Principal / identity | A thing that can attempt actions (a user or an assumed role). |
| IAM user | Long-lived identity with permanent credentials. Avoided here. |
| IAM role | Credential-less identity that approved principals *assume* temporarily. |
| Trust policy | On a role: **who may assume it.** |
| Permission policy | On a role: **what the wearer may do.** |
| ARN | Globally unique name for an AWS thing; supports `*` wildcards. |
| Statement | One Allow/Deny rule (Effect + Action + Resource + Condition). |
| Deny-wins | An explicit Deny always beats any Allow; you can't except a Deny with an Allow. |
| Condition | Contextual test on a statement; `StringNotEquals` also passes when the key is absent. |
| STS / AssumeRole | The call that hands out a role's temporary credentials. |
| Instance profile | Wrapper letting an EC2 instance wear a role. |
| Instance metadata (`169.254.169.254`) | Where an instance reads its own live credentials. |
| `PassRole` | Permission to hand a role to a service; the guard on "give this instance that role." |
| Service-linked role | AWS-managed helper role under `aws-service-role/`; made via a *distinct* action. |
| Permissions boundary | A ceiling on a role's effective power: effective = grants ∩ boundary. |
| OIDC federation | How an external identity (GitHub) assumes an AWS role without a stored secret. |

Next: [the deployer permissions boundary](deployer-permissions-boundary.md),
which puts every one of these to work.
