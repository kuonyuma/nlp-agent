# 0003 — Preserve disabled Topics instead of deleting them

## Decision

Topics have `enabled` and `disabled` states. Teachers can stop and later re-enable a Topic. Disabled Topics are not returned as selectable learner Topics and cannot start new teaching sessions.

Knowledge Points follow the same lifecycle. Their editable instructional content is stored as Markdown, and only enabled Knowledge Points constrain newly assembled teaching prompts or are eligible for new blueprint assignment.

## Consequences

Existing chat Turns, teaching sessions, evidence, and blueprint snapshots retain their Topic association and display-name snapshot. Analytics remains historically accurate, and re-enabling restores the Topic without migration. Physical deletion is not part of the teacher workflow.
