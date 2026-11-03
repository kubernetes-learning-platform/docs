# Copilot instructions: docs

This is the documentation hub of kubernetes-learning-platform, an AI tutor with a live Kubernetes lab. `ARCHITECTURE.md` is the plan (repos, services, contracts, flows, milestones, risks). `FEATURES.md` explains each feature twice, once from the user's view and once technically. `PROJECT-BRIEF.md` is the original brief. Where they disagree, `ARCHITECTURE.md` wins.

## When reviewing, focus on
- **Decision labels.** Statements are tagged **DECIDED**, **DEFAULT**, **OPEN** or **CALL**. Keep the labels. Flag a change that quietly turns an OPEN item into a decision without saying so in the PR.
- **Consistency across documents.** Repo names (`docs`, `contracts`, `sandbox`, `api`, `web`, `platform`), package names (`KubernetesLearning.*`, `@kubernetes-learning-platform/contracts`), the proto package (`kubernetes_learning.v1`), controller and message names should match between README, ARCHITECTURE and FEATURES.
- **Links and anchors.** Relative links and `#section` anchors still resolve after headings change.
- **Diagrams.** Mermaid diagrams stay small and readable (a handful of boxes). Detail belongs in tables and folder trees.
- **People.** Teammates are referred to as Filip, Person 2 and Person 3.
- **Naming.** "kubernetes-learning" is a placeholder name.

## Project-wide rules
- PR titles are Conventional Commits (`docs: short description`), one line, at most 72 characters, no trailing period.
- Files are UTF-8 with LF line endings.

## Don't
- Don't rewrite prose for style unless it's unclear or wrong.
- Keep reviews short. Skip praise and summaries of the diff.
