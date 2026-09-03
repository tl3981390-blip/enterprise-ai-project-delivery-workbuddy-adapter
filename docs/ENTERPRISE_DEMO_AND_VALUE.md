# Enterprise Demonstration and Value Contract

This is a demonstration contract for `enterprise-ai-project-delivery` on
WorkBuddy.  It is deliberately evidence-led: a presenter must show only the
claims whose prerequisites are PASS in the local preflight and live-session
audit.

## The enterprise problem

Most general Skills help a model perform one specialised action.  The enterprise
failure is usually not that the model cannot edit a file; it is that a
multi-step project has no trustworthy delivery control:

| Enterprise risk | What a conventional one-purpose Skill normally leaves to the user | What this Delivery Controller adds |
| --- | --- | --- |
| Goal drift | The user repeatedly restates the objective and checks every step. | A delivery session ties visible work to the original goal and current scope. |
| False completion | A green-looking response can be mistaken for evidence. | Completion is held by a Stop/Evidence gate until registered, current evidence exists. |
| Untrusted control | The model can treat its own prose as a user approval, pause, or cancellation. | The host captures the user message verbatim; any control declaration is anchored to that real message, replay-protected, and audited. |
| Failure recovery | The model may paper over a failure and continue. | Failure and recovery are recorded against work units; recovery needs re-validation. |
| Governance visibility | Teams get a chat transcript but cannot see the basis for an outcome. | Hook event, bridge decision, work unit, artifact, and Core evidence are linked in an audit trail. |

The product is therefore not a replacement for a company's specialist Skills.
It is the delivery layer that governs when a suitable specialist capability may
be used, contains it to the relevant work unit, and prevents a successful-looking
answer from being called a completed project without evidence.

## What is proven on this WorkBuddy integration

The following claims have real-machine evidence on this adapter branch:

1. A project-scoped WorkBuddy command-hook can send genuine
   `UserPromptSubmit`, `PostToolUse`, and `Stop` events to the bridge without
   changing WorkBuddy global settings.
2. The bridge can create a formal Core delivery session from a real user goal,
   record registered `PostToolUse` artifacts into the Canonical Evidence Ledger,
   and use the Stop gate to withhold completion when the evidence contract is
   open.
3. User-controlled transitions are not created by a keyword table.  The model
   must explicitly declare a meaning for a *real, captured* user message; forged,
   stale, cross-session, and replayed origins are rejected.  High-impact or
   ambiguous Cancel/Correction readings require a subsequent user confirmation.
4. The formal Delivery Core is self-contained and identity-checked by the
   read-only preflight (`INSTALL_INFO.json` / canonical tag-to-commit identity).

Run before a customer demonstration:

```powershell
python -B src/probe_workbuddy.py --workbuddy-home $env:USERPROFILE\.workbuddy
```

Then start one fresh project session and retain its project-local audit output.
The preflight is not a substitute for that real session; it makes any missing
condition visible *before* the customer sees a claim.

## Automatic selection of existing WorkBuddy Skills

This is the intended product experience:

```text
ordinary user goal
  -> understand work units
  -> read the Host-attested current-session capability list
  -> choose the smallest sufficient eligible Skill
  -> invoke it for that work unit
  -> record its result as evidence
  -> clean up the capability scope
```

The Controller already implements the candidate validation, deterministic
selection, invocation boundary, and evidence binding.  It accepts a capability
list only when WorkBuddy supplies it in a genuine `PostToolUse` receipt with
identity, description, availability, and permission state.

**Current WorkBuddy boundary:** the `/skills` display is generated in the
desktop UI and its documented Hook, plugin, and HTTP interfaces do not return
that current-session list to a project Controller.  A receipt merely saying
`/skills` ran is rejected.  Model-transcribed lists, filesystem scans, and
hard-coded Skills are also rejected.  Therefore this capability is
`NOT_INCLUDED_BY_DESIGN` for the currently tested WorkBuddy demonstration
integration.

Do not demonstrate automatic selection as PASS until the preflight/live receipt
contains the Host-attested list and the Router decision plus actual invocation
are present in the session audit.  This restriction is a safeguard against
misrepresenting an enterprise control as a prompt trick.

## Recommended customer demonstration

### Phase A — reliable project delivery (demonstrable now)

1. Run the read-only preflight and show the formal Core identity result.
2. Start a small existing project with a normal request, for example:

   > 接手这个项目。先理解现在的实现和约束，完成剩余工作；只有通过真实验证后再告诉我完成。

3. Let the model inspect the existing work, show a human-readable plan containing
   real project work, and execute verification.
4. Introduce a safe, pre-prepared failure such as an invalid configuration.  The
   correct demonstration is diagnosis, safe pause when Owner input is required,
   authorised recovery, re-validation, then evidence-backed completion.
5. Show the audit mapping: real Host event → bridge decision → Core operation →
   evidence record.  This is the practical difference from an ordinary Skill
   returning a confident paragraph.

### Phase B — capability composition (only after the Host gate passes)

1. Preinstall at least two innocuous WorkBuddy Skills with clearly distinct
   descriptions in the demonstration environment.
2. Run `/skills` through the official mechanism and verify that the
   `PostToolUse` receipt contains the actual current-session list.
3. Give only a normal business goal.  Do not name a Skill in the user request.
4. Show the Router candidate list, exclusions, selected minimal capability,
   actual Skill invocation, and the scoped evidence record.

If step 2 does not produce the list, stop Phase B and say exactly why.  Continue
with Phase A; never replace the missing Host data with a hand-written list.

## Presenter claims

Use these statements:

- “This does not compete with your existing specialist Skills; it provides the
  delivery control that lets an AI compose them around a real project safely.”
- “The user says the goal in normal language.  The Controller keeps the model
  tied to scope, permissions, evidence, and user authority.”
- “A model response is not treated as project completion.  Completion must be
  backed by real artifacts and current evidence.”
- “Where the Host exposes a trustworthy capability list, the Controller can
  select the minimal sufficient existing Skill rather than making the user
  choose.  This WorkBuddy build has not yet exposed that list to its official
  integration surface, so we label it pending rather than pretending it works.”

Do not say “all WorkBuddy Skills are automatically selected” on this build.
