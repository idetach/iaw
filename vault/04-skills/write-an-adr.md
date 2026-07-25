---
title: "Skill: Write an ADR"
tags: [skill]
updated: 2026-07-25
---

# Skill: Write an ADR

Use whenever you make a decision that is expensive to reverse or that a future
reader would ask "why did we do it this way?"

## Steps
1. Copy [[_adr-template]] to `02-decisions/ADR-NNNN-<slug>.md` (next number).
2. Fill **Context** with the forces and constraints — link relevant notes.
3. State the **Decision** in one or two plain sentences.
4. List **Consequences** honestly, including the trade-offs you accept.
5. List **Alternatives considered** and why each lost.
6. Set `status: proposed`. When adopted, flip to `accepted`.
7. Link the new ADR from [[README]] and any affected architecture/strategy note.

## Rules
- One decision per ADR.
- **Never edit an accepted ADR.** If it changes, write a new ADR that
  `supersedes` it and set the old one's `superseded-by`.
- Keep it short. An ADR is a record, not an essay.
