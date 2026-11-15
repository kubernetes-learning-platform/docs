# AGENTS.md: docs

Instructions for AI coding agents working in this repository. `CLAUDE.md` is a symlink to this file, so Claude Code reads the same instructions.

## What this repo is

The documentation hub of kubernetes-learning-platform, a live Kubernetes lab with an optional AI helper. Every other repo links here for the overall design.

| File | What's in it |
|---|---|
| `README.md` | Project hub: overview, architecture, repo map, workspace layout, conventions, team, roadmap |
| `ARCHITECTURE.md` | The main reference: repos, services, contracts, flows, folder trees, CI/CD, milestones, risks |
| `FEATURES.md` | Every feature twice: what the user sees, then how it works |
| `PROJECT-BRIEF.md` | The original brief. Kept for history, with notes where later decisions replace it |
| `adr/` | Architecture decision records, one per decision |
| `assets/diagrams/` | `generate.py` and the SVG sheets it writes |

- **Owner:** Filip. Everyone contributes.
- **Status:** current. The code repos are still empty, so these documents describe the plan.
- **Precedence:** where documents disagree, the ADRs and `ARCHITECTURE.md` win over `README.md`, `FEATURES.md` and `PROJECT-BRIEF.md`.

## Layout

```
docs/
├── README.md
├── ARCHITECTURE.md
├── FEATURES.md
├── PROJECT-BRIEF.md
├── adr/                    # 0001 harness transport, 0002 learner-driven scenarios, 0003 course VM hosting
├── assets/diagrams/        # generate.py + <sheet>-{light,dark}.svg
└── .github/                # copilot-instructions.md, PR template, workflows
```

## Build and check

There is nothing to build. Before saying a change is done:

- Check that relative links and `#section` anchors still resolve, especially after renaming a heading.
- If a diagram changed, run `python3 assets/diagrams/generate.py --sync` from this repo's root. It rewrites the SVGs here and copies each repo's own sheet into `../<repo>/assets/`. Those copies are changes in the other repos and need their own commits.

## Writing rules

- **Decision labels.** Statements carry **DECIDED** (agreed), **DEFAULT** (proposed, not objected to), **OPEN** (not decided) or **CALL** (chosen while writing, change freely). Keep them, and never turn an OPEN item into a decision without saying so.
- **ADRs.** A new decision gets a new ADR, or a dated revision of an existing one with its status line updated. A superseded ADR keeps its text; only its status line changes to say what replaced it.
- **Consistency.** Repo names, package names (`KubernetesLearning.*`, `@kubernetes-learning-platform/contracts`), the proto package (`kubernetes_learning.v1`), controller and message names match across `README.md`, `ARCHITECTURE.md`, `FEATURES.md` and the ADRs.
- **Diagrams.** Edit the sheet's definition in `generate.py`, never an SVG. Keep sheets small, about ten boxes, and put detail in tables and folder trees. When a sheet changes, update the `alt` text where it is embedded.
- **People.** Teammates are Filip, Person 2 and Person 3.
- **Naming.** "kubernetes-learning" is a placeholder name.
- **Hosting.** Call the machine "the course-provided VM" or "the course VM", without naming the institution.
- **Scale.** The 30-sandbox target is a neutral design target with no backstory. Users are "learners".

## Commits, branches and PRs

- **Always ask the user before creating a branch, committing or pushing.** Show the commit message when you ask.
- **Commits:** Conventional Commits only, one line: `type: short description`, lowercase, no trailing period. No body. No `Co-Authored-By` or any other attribution.
- **Types:** `feat`, `fix`, `docs`, `refactor`, `perf`, `test`, `build`, `ci`, `chore`, `revert`, `style`. Changes in this repo are almost always `docs`.
- **Branches:** use the name in the `Branch:` line of the issue being worked on. Don't make one up. `gh issue develop <number> --name <branch> --checkout` creates it linked to the issue.
- **Where changes land:** while the code repos are still empty, documentation goes straight to `main`. Once the setup issues are under way, changes go through a PR.
- **PRs:** the title follows the commit format, at most 72 characters; it becomes the squash commit on `main`. The description is one or two plain sentences, plus `Closes <repo>#<number>` when there is an issue. Merging needs one approval from someone other than the author, and the branch must be up to date with `main`. Filip is requested as reviewer on every PR (`.github/CODEOWNERS`), and the author is assigned automatically. Only Filip merges.
- **Public repo:** everything committed is public at once. Never commit secrets, real `.env` files or personal data; push protection only catches known token formats.

## Keep docs in sync

When a change touches this repo's layout or conventions, update `AGENTS.md`, `README.md` and `.github/copilot-instructions.md` in the same change.

The other repos restate design facts from here in their `README.md`, `AGENTS.md` and `.github/copilot-instructions.md`. When a design fact changes here, update those files in the affected repos as part of the same piece of work, and mention it to the user.

## Writing style

Plain, professional wording. No emoji, no marketing tone. Files are UTF-8 with LF line endings, following `.editorconfig`.
