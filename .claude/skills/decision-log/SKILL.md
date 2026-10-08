---
name: decision-log
description: Record an engineering decision (what, alternatives, why, tradeoff) in docs/DECISIONS.md
disable-model-invocation: true
argument-hint: "[short description of the decision]"
---

Add one entry to `docs/DECISIONS.md` (create the file with a `# Decisions` heading if it does not exist). Append at the end, never rewrite existing entries.

The decision: $ARGUMENTS

If the arguments are empty, summarize the most recent significant decision from this conversation instead.

Use exactly this format:

```
## <short title>
- **Decision:** what we chose
- **Alternatives considered:** the realistic options, one line each
- **Why:** the reason, tied to the task constraints (time budget, requirements, grading criteria)
- **Tradeoff / what I'd do with more time:** the honest downside
```

Keep it under 8 lines. Be specific, not generic. If something is an assumption rather than a decision, say so in the title.
