# NLP Learning Context

This context defines the educational catalogue and learner interactions used by the NLP learning assistant.

## Language

**Topic**:
A teacher-owned curriculum unit with an immutable `topic_id`, editable display name, and teacher-controlled enabled/disabled status. Knowledge points and blueprints belong to a Topic; learner state refers to its ID. Disabled Topics are unavailable for new learner selection or teaching sessions, but remain recoverable and preserve historical associations.
_Avoid_: topic name as identity, hard deletion, course label

**Knowledge Point**:
A teacher-owned, Markdown-authored unit of teachable scope within a Topic, with immutable `knowledge_point_id`, editable title and Markdown body, and enabled/disabled status. Enabled Knowledge Points constrain the topic’s instructional scope and are eligible for new prompts, exercises, and reviews; disabled ones remain available only to historical records and snapshots.
_Avoid_: plain tag, immutable content, hard deletion

**Knowledge-Point Injection**:
The ordered, length-bounded Markdown collection of every enabled Knowledge Point for the current Topic, assembled by the backend for a new prompt. If it exceeds the configured budget, the system reports this teacher-configuration problem rather than silently changing the teaching scope.
_Avoid_: implicit semantic retrieval, silent truncation

**Learning Selection**:
The student's optional Topic plus level and mode preferences. Its defaults are no Topic, `beginner`, and `explain`. With no Topic selected, Topic and Knowledge-Point prompt content is empty; with a Topic selected, the learner's current question still takes priority over the Topic boundary while level and mode remain in effect.
_Avoid_: mandatory default Topic, automatic Topic classification

**Guided Session**:
A structured Socratic-learning state linked to one chat Session. It records the learning objective, current step, learner responses, and misconceptions without replacing chat history.
_Avoid_: guided chat, prompt-only guidance

**Exercise Session**:
A structured practice or review attempt linked to one chat Session and a snapshot of a blueprint. It records generated questions, rubric, attempts, answers, scores, and lifecycle state without replacing chat history.
_Avoid_: exercise turn, temporary quiz

**Active Teaching Session**:
The sole unfinished Guided Session for a chat Session and Topic, or an unfinished Exercise Session selected for the current mode. Completed, cancelled, and expired teaching sessions are history only and are never injected into a Prompt.
_Avoid_: latest session, current chat state

**Blueprint Snapshot**:
An immutable copy of an exercise or review blueprint stored when an Exercise Session starts. It is the authoritative instructions and rubric for that attempt.
_Avoid_: live blueprint reference, mutable attempt template

**Blueprint**:
A teacher-owned practice or review definition under one Topic. It combines structured fields—status, ordered Knowledge Point references, question count and types, difficulty, scores, and weighted rubric points—with editable Markdown instructions for generation and feedback. The Markdown may describe or render fill-in, multiple-choice, tabular, mathematical, code, and coordinate-graph questions.
_Avoid_: Markdown-only unscored template, rigid question-only schema

**Teaching Markdown**:
The restricted Markdown subset used for generated questions, explanations, and feedback: prose, lists, tables, code, formulas, and Mermaid diagrams. Raw HTML, scripts, and arbitrary external embeds or links are not rendered.
_Avoid_: trusted model HTML, executable question content

**Blueprint Assignment**:
The server-only selection of one eligible exercise or review blueprint from the current Topic when a teaching session starts. Students never choose or see the blueprint; the selected blueprint is captured as a snapshot.
_Avoid_: student-selected blueprint, live template lookup

**Blueprint Status**:
The teacher-controlled availability of a blueprint: draft is editable but unavailable, enabled is eligible for server assignment, and disabled is retained but unavailable.
_Avoid_: deleted draft, implicit availability

**Teaching Session Start**:
The first learner message sent in a teaching mode, which is the only trigger for creating a Guided Session or Exercise Session. Changing a mode selector alone creates no record.
_Avoid_: mode-change session, empty teaching session

**Guided Objective**:
The learner's first message in guided mode, retained as the learning objective until the learner explicitly changes objective or Topic.
_Avoid_: inferred objective, classifier-generated objective

**Teaching Session Expiry**:
The transition of an active teaching session to history after explicit completion, Topic or mode change, or 30 minutes without a learner message. Expiry never closes the linked chat Session.
_Avoid_: chat timeout, transcript deletion

**Learning Evidence**:
The structured, non-reasoning record of an exercise attempt: blueprint snapshot, question, rubric matches, score, learner answer, attempt count, associated Knowledge Points, and completion time. It is the source for review selection and teacher analytics.
_Avoid_: model chain of thought, transcript-only analytics

**Rubric Score**:
A normalized 0–100 score calculated from teacher-defined weighted rubric points, alongside the individual point matches. Natural-language feedback does not determine the score.
_Avoid_: prose-only grading, unweighted pass/fail

**Grading Result**:
A backend-validated structured result for an Exercise attempt: per-rubric-point match and score, normalized total, pass state, and concise feedback. The result is accepted only when it conforms to the Exercise Session's Blueprint Snapshot; natural-language commentary cannot override it.
_Avoid_: unvalidated model score, prose-controlled grading

**Legacy Topic Migration**:
On first read, a legacy topic name is mapped to a `topic_id` only when it uniquely matches the teacher catalogue. Missing or ambiguous names remain unclassified. Historical Turns are not bulk-rewritten; new Turns store `topic_id` plus a display-name snapshot.
_Avoid_: guessing a matching topic, rewriting historical transcripts
