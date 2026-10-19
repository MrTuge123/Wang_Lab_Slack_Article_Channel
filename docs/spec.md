# Literature Fetch on AWS — Project Spec

Oct 4, 2026 · @Tiger

## Goal and scope

Turn the `slack_post` digest into a website where invited users sign in, set their research preferences, and get a weekly paper digest, all running serverless on AWS for about $0 a month.

**In scope (v1)**

- Invite-only sign-up with email verification
- One preferences form per user, the same fields as `subscribers/_template.yaml`
- Delivery to Slack (the user's own webhook) or email
- The weekly digest run moves from GitHub Actions to AWS
- A "preview my query" button and a page of past digests

**Out of scope (v1)**

- Open public sign-up, payments, mobile app
- WeCom delivery (add back later)
- Real-time or daily digests

**Done means:** a lab member you invite can sign up, save preferences, and receive Monday's digest without you touching the repo.

## Decisions

| Area | Choice | Why |
| --- | --- | --- |
| Users | Lab + invited (invite codes) | Caps LLM cost and spam |
| Frontend | React + Vite + TypeScript, static build | Industry standard; Claude Code handles it well |
| Backend | Python 3.12 on Lambda | Reuses the existing `digest/` package |
| Infrastructure as code | AWS CDK in Python | Whole stack in code, rebuildable in one command |
| Database | DynamoDB, single table | Always-free 25 GB; no server to run |
| Auth | Cognito user pool | Always-free up to 10,000 users a month |
| API | API Gateway HTTP API + Cognito JWT authorizer | Checks the login token for you; about $1 per million calls, so effectively $0 |
| Secrets | SSM Parameter Store, SecureString | Standard tier is free; Secrets Manager is not |
| Region | us-east-1 | Every service available; CloudFront certs live there |
| AI coding | Claude Code, one milestone per session | You review each diff before moving on |

## Architecture

&#91;embedded content: architecture · site path and Monday digest path\]

The site only reads and writes settings; the Monday job does the heavy work one user at a time. Both meet at the DynamoDB table and Parameter Store, so neither depends on the other being up.

## Data model

One DynamoDB table, `LitFetch`, with keys `PK` and `SK`. Each user's items share `PK = USER#<cognito sub>`, so one query loads everything about a user.

| Item | PK | SK | Main attributes | Replaces |
| --- | --- | --- | --- | --- |
| Profile | `USER#<sub>` | `PROFILE` | email, display\_name, status (active / paused), created\_at | — |
| Preferences | `USER#<sub>` | `PREFS` | query or topic, interest, sources, journals, days\_back, max\_papers, ranking, outputs, chinese\_summary, updated\_at | `subscribers/<name>.yaml` |
| Seen paper | `USER#<sub>` | `SEEN#<paper id>` | first\_sent\_at, ttl (auto-delete after 1 year) | `seen/<name>.json` |
| Past digest | `USER#<sub>` | `DIGEST#<YYYY-MM-DD>` | papers, summaries, delivery status | `history/` |
| Invite | `INVITE#<code>` | `META` | created\_by, used\_by, expires\_at | — |

- **Webhook URLs never go in the table.** Store each one in Parameter Store at `/litfetch/webhooks/<sub>` as a SecureString. The table only records that one exists.
- **Validation:** one Pydantic model, `Preferences`, is the single source of truth. The API, the digest Lambda, and a YAML import script all use it.
- **Finding active users:** a Scan on `SK = PREFS` is fine at lab scale (under 100 users). Add an index later if needed.
- **Migration:** a one-off script loads the current `subscribers/*.yaml` and `seen/*.json` into the table.

## API

One Lambda (`api`) behind an HTTP API serves every route. It uses AWS Lambda Powertools for routing and logging. Every route except the health check requires a Cognito login token; the user id always comes from the token, never from the request body.

| Method | Path | Does | Notes |
| --- | --- | --- | --- |
| GET | `/health` | Returns ok | No login |
| GET | `/me` | Profile + preferences | Creates the profile on first call |
| PUT | `/me/preferences` | Validate and save preferences | 400 with field errors if invalid |
| PUT | `/me/webhook` | Save Slack webhook URL to Parameter Store | Must start with `https://hooks.slack.com/` |
| DELETE | `/me/webhook` | Remove webhook |  |
| POST | `/me/preview` | Run the query only, return match count + 5 titles | No LLM calls; 25 s limit |
| POST | `/me/test-delivery` | Send a short test message | Rate limit: 3 a day |
| GET | `/me/digests` | List past digests, newest first | Paginated |
| DELETE | `/me` | Delete account and all items |  |
| POST | `/admin/invites` | Create invite codes | Cognito `admins` group only |

**Invite check:** a Cognito pre-sign-up Lambda rejects sign-ups without a valid, unused invite code and marks the code used.

**Errors:** JSON `{"error": "<code>", "message": "..."}` with 400 / 401 / 403 / 404 / 429 / 500.

## Frontend

A React + Vite single-page app, built to static files in S3 and served through CloudFront. Login uses the Amplify JS library's `Auth` module with your Cognito pool; Amplify Hosting itself is not used.

| Page | Path | Shows |
| --- | --- | --- |
| Landing | `/` | What it does, Sign in, Sign up with invite code |
| Sign up / sign in | `/login` | Email + password, email verification code, invite code |
| Preferences | `/settings` | The form below, Save, Preview, Send test |
| Past digests | `/digests` | List by date; click to read papers and summaries |
| Account | `/account` | Pause digests, delete account |
| Admin | `/admin` | Create invite codes (admins only) |

**Preferences form** (fields mirror `_template.yaml`):

1. **Topic:** a choice between a plain-English topic or an advanced boolean query, plus an optional interest sentence
2. **Sources:** checkboxes for PubMed (always on), Europe PMC, OpenAlex, Semantic Scholar, arXiv
3. **Filters:** journals (tag input), days back (1–30), max papers (1–10)
4. **Ranking:** preferred authors, preferred journals, key words (tag inputs), minimum relevance (0–10 slider), minimum author h-index
5. **Delivery:** Slack (webhook URL, write-only) and / or email; Chinese summary toggle per channel

Built with React Hook Form + Zod for client-side checks; the server re-checks with Pydantic.

## Digest pipeline refactor

The weekly run becomes one small job per user, because a Lambda stops after 15 minutes and today's run takes up to 45.

1. **Schedule:** EventBridge Scheduler fires Mondays 7:00 `America/New_York`, same as today.
2. **Dispatch Lambda:** reads every active user's `PREFS` and puts one SQS message per user: `{"user": "<sub>", "run_date": "YYYY-MM-DD"}`.
3. **Queue:** SQS `digest-jobs`, visibility timeout 16 min, dead-letter queue after 3 failed tries.
4. **Worker Lambda:** batch size 1, timeout 15 min, **reserved concurrency 1** so only one user runs at a time and Kimi's \~3 calls per minute is respected. It loads preferences, runs the existing `digest/` logic, writes `SEEN#` and `DIGEST#` items, then delivers.
5. **Delivery:** Slack via the webhook in Parameter Store; email via SES.

**Code changes in `digest/`**

- Split "load config" from "run": a function `run_subscriber(prefs, store, secrets)` that never touches files directly.
- A `Store` interface with two versions: `FileStore` (today's `seen/` and `history/` folders, for local runs) and `DynamoStore`.
- API keys come from Parameter Store at cold start instead of `.env` (keep `.env` for local).
- `python main.py --subscriber <name>` keeps working locally, so you can debug without AWS.
- Add `pytest` tests for `run_subscriber` with a fake store and a mocked LLM before moving anything.

**Cut-over:** run AWS and GitHub Actions side by side for two Mondays (AWS sending only to a test Slack channel), compare outputs, then disable the GitHub workflow.

## Security and cost guardrails

**Security**

- [ ] MFA on your AWS Builder ID (two devices) and a recovery email
- [ ] Least privilege: each Lambda gets its own role that touches only its table, queue and parameters (CDK `grant_*` methods do this)
- [ ] No secrets in code or in the frontend bundle; `.env` stays in `.gitignore`
- [ ] User id comes only from the login token; every DynamoDB key is built from it
- [ ] Webhook URLs are write-only in the UI and never returned by the API
- [ ] S3 bucket private, readable only through CloudFront (Origin Access Control)
- [ ] CORS on the API allows only the CloudFront domain
- [ ] API throttling: 10 requests per second per route

**Cost**

- [ ] Billing alarms at $1 and $5, plus an AWS Budget with email alerts
- [ ] Serverless only: no EC2, RDS, NAT Gateway, or public IPv4 addresses
- [ ] Cap active users at 30 in config until LLM cost is measured
- [ ] Log each digest's LLM token count to the `DIGEST#` item; review monthly
- [ ] CloudWatch log retention: 14 days
- [ ] Before the Free plan's 6 months end, upgrade to the Paid plan so always-free services continue
- [ ] `cdk destroy` tears everything down if you ever want to stop

## Build plan

Start with M0 today: set up the AWS account safely, before writing any code. Each milestone ends with something you can see working, and gets its own git branch, Claude Code session and commit.

**How to vibe code each milestone**

- Export this doc to Markdown as `docs/SPEC.md` in the repo, and add a `CLAUDE.md` that says: "Follow docs/SPEC.md. Python 3.12, CDK in `infra/`, frontend in `web/`. Explain every AWS resource you add. Never put secrets in code."
- Start each session in **plan mode**; read the plan and ask "why" about anything unclear before approving.
- After each diff, ask Claude Code: "Explain what this does line by line and what it costs on AWS."
- Run the Verify step yourself before moving on.

### M0 — AWS account and tools (1 evening)

- **Context:** the account uses AWS's new "projects" sign-in. You sign in with an AWS Builder ID to the project **Index Zero**; there is no separate root login or IAM Identity Center to set up
- **Learn:** Builder ID vs IAM, MFA, AWS Budgets, temporary CLI credentials (`aws login`), CLI profiles
- **Do (by hand, no AI):** account menu → **Profile** → **Security**: add a recovery email, register two MFA devices (Mac Touch ID passkey + phone authenticator); console search "Budgets" → a zero-spend budget and a $5 monthly budget; install AWS CLI 2.32+ and Node 20+, `npm i -g aws-cdk`; `aws login --profile litfetch` (choose Index Zero in the browser); `cdk bootstrap --profile litfetch`
- **Later (M2):** the console's "Copy agent prompt" connects Claude Code to the project through AWS's MCP server; do it after budgets are set
- **Verify:** `aws sts get-caller-identity --profile litfetch` returns your project's account id

### M1 — Refactor the pipeline locally (no AWS)

- **Learn:** Pydantic models, dependency injection (the `Store` interface), pytest with mocks
- **Prompt:** "Read docs/SPEC.md, sections Data model and Digest pipeline refactor. Plan how to add a `Preferences` Pydantic model, a `Store` interface with `FileStore`, and `run_subscriber(prefs, store, secrets)`, keeping `main.py --subscriber` behavior identical. Add pytest tests with a mocked LLM."
- **Verify:** `pytest` passes; `python main.py --subscriber _slack_test` posts the same digest as before

### M2 — CDK app + DynamoDB + migration

- **Learn:** CDK apps, stacks and constructs, `cdk synth / diff / deploy`, DynamoDB keys and single-table design
- **Prompt:** "Create a CDK Python app in `infra/` with the `LitFetch` table from the spec (on-demand billing, TTL on `ttl`, point-in-time recovery off). Then write `scripts/migrate_yaml.py` that loads `subscribers/*.yaml` and `seen/*.json` into it via `DynamoStore`."
- **Verify:** `cdk diff` shows only the table; after the migration, the DynamoDB console shows your lab's `PREFS` and `SEEN#` items

### M3 — Digest worker on Lambda

- **Learn:** Lambda packaging (CDK `PythonFunction` or a container), IAM roles, Parameter Store, CloudWatch Logs
- **Prompt:** "Add the worker Lambda from the spec: 15-min timeout, reads API keys from Parameter Store under `/litfetch/`, runs `run_subscriber` for one user id from the event. Grant only the permissions it needs."
- **Do by hand:** put your Moonshot / Groq / NCBI / OpenAlex keys and the test webhook into Parameter Store as SecureStrings
- **Verify:** invoke it from the console with your own user id; the test Slack channel gets a digest; logs show token counts

### M4 — Schedule, dispatch and queue

- **Learn:** EventBridge Scheduler, SQS, dead-letter queues, reserved concurrency
- **Prompt:** "Add the dispatch Lambda, the `digest-jobs` SQS queue with a DLQ, and a Mondays 7:00 America/New\_York schedule, as in the spec. Worker batch size 1, reserved concurrency 1."
- **Verify:** run the schedule once by hand; every active user gets processed one at a time; a forced failure lands in the DLQ

### M5 — Login and API

- **Learn:** Cognito user pools, JWTs, HTTP API authorizers, Lambda Powertools routing, CORS
- **Prompt:** "Add a Cognito user pool with email sign-in, an `admins` group, and a pre-sign-up Lambda that checks invite codes. Then the `api` Lambda with the routes in the spec behind an HTTP API with a Cognito JWT authorizer. Tests for every route."
- **Verify:** create a user with an invite code via the CLI, get a token, and `curl` `GET /me` and `PUT /me/preferences`; a bad token gets 401

### M6 — Frontend, running locally

- **Learn:** React components and state, React Router, forms with React Hook Form + Zod, calling an API with a login token
- **Prompt:** "Create a Vite React TypeScript app in `web/` with the pages in the spec. Use Amplify JS Auth only for Cognito. Read the API URL and pool ids from `.env.local`. Keep styling simple (Tailwind)."
- **Verify:** `npm run dev`; sign up with an invite, fill the form, Preview shows matching titles, Send test reaches Slack

### M7 — Deploy the website

- **Learn:** S3 static hosting, CloudFront, Origin Access Control, cache invalidation
- **Prompt:** "Add a CDK stack that deploys `web/dist` to a private S3 bucket behind CloudFront with OAC and SPA routing (404 → index.html). Lock the API's CORS to the CloudFront domain."
- **Verify:** the `*.cloudfront.net` URL works on your phone; the S3 bucket URL itself is denied

### M8 — Email delivery and past digests

- **Learn:** SES identities, sandbox vs production access, email HTML
- **Do by hand:** verify a sender email in SES; request production access
- **Prompt:** "Add email delivery via SES to the worker and the Past digests page."
- **Verify:** a test user with email-only delivery gets Monday's digest

### M9 — Cut-over, monitoring and CI

- **Learn:** CloudWatch alarms, GitHub Actions deploying to AWS through OIDC (no stored AWS keys)
- **Prompt:** "Add CloudWatch alarms for DLQ messages and Lambda errors that email me. Add a GitHub Actions workflow that runs tests and `cdk deploy` on push to main using an OIDC role."
- **Verify:** two Mondays of matching output from AWS and GitHub; then disable `.github/workflows/digest.yml` and invite the lab

## Open questions

- [ ] Who pays for Kimi once more people join: you, the lab, or a cap per user?
- [ ] Lab-wide digest (today's `wang_lab.yaml` to one shared Slack channel): a special "group" user owned by you, or a real group feature?
- [ ] Should users bring their own Slack webhook, or should you install one Slack app for the lab?
- [ ] Custom domain (about $15 a year) or the free `*.cloudfront.net` address?
- [ ] Share LLM work across users with overlapping topics (rank each paper once) — needed above about 30 users
- [ ] Keep WeCom delivery? It is in the current code but out of scope for v1
