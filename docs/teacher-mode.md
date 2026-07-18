# Teacher mode

Teacher mode shares the primary FastAPI/WebUI origin with student mode:

- student: `/`
- teacher: `/teacher/*`
- developer: `/developer/*`

The current local deployment issues an administrator session, so it can enter
teacher mode. The authorization boundary already accepts either `admin` or
`teacher`; a future identity provider only needs to issue the role and allowed
workspace IDs.

## Routes

| UI route | Purpose |
|---|---|
| `/teacher` | Overview, teaching goals, question and weakness summary |
| `/teacher/courses` | Teaching-goal editor and reserved course list |
| `/teacher/prompts` | Reserved Prompt/course/report template interfaces |
| `/teacher/questions` | Classified student question records |
| `/teacher/reports` | Frequent questions, weak topics and distributions |

## API contracts

| Method and path | Purpose |
|---|---|
| `GET /api/v1/teacher/overview` | Goals and all local analytics in one dashboard payload |
| `GET /api/v1/teacher/goals/{workspace_id}` | Read workspace teaching goals |
| `PUT /api/v1/teacher/goals/{workspace_id}` | Update teaching goals; same-origin + CSRF required |
| `GET /api/v1/teacher/questions` | Classified question records |
| `GET /api/v1/teacher/analytics` | Aggregates without individual question rows |
| `GET /api/v1/teacher/courses` | Reserved course repository boundary |
| `GET /api/v1/teacher/prompts` | Reserved template repository boundary |
| `GET /api/v1/teacher/reports` | Reserved durable-report repository boundary |

All query APIs accept `workspace_id`; analytics endpoints also accept `days`.
The service validates teacher/admin role and workspace access before querying.

## Local-first analysis

Until account allocation, PostgreSQL, and Redis are introduced, the read model
uses existing `gateway_turns` rows. It performs deterministic local processing:

- strips the hidden student learning-context envelope;
- classifies NLP topic and question type with an explicit rule catalog;
- respects the student's declared difficulty when present;
- groups normalized repeated questions;
- derives weak-topic risk from question volume, repetition, difficulty, and
  answer errors;
- returns topic, difficulty, and question-type distributions.

No additional model call, vector database, RAG pipeline, or cache is required.
The stable service/repository boundary allows a later SQL analytics job or model
classifier to replace the implementation without changing the WebUI contract.

Teaching goals currently reuse the Gateway's local versioned settings storage.
They are namespaced by `teacher_goals:{workspace_id}`. A future course database
can migrate this record behind `TeacherService`.
