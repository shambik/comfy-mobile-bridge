---
name: git-standards
description: Git conventions for branches, commits, pull requests, tags, and history maintenance.
---

# Git standards

## Trigger

Use this skill before creating branches, committing, opening a PR, merging,
tagging, pushing, or cleaning Git history.

## Rules

Commit and PR subjects use:

    type(scope): short imperative summary

Types: feat, fix, perf, refactor, docs, test, build, ci, chore, revert.
Scopes: app, backend, ui, bootstrap, comfy, models, tailscale, docs, tests,
ci, deps, release. Use English, lowercase type and scope, no final period, and
no more than 72 characters. Wrap a body at 100 characters. Use BREAKING
CHANGE: for breaking behavior.

Branches use <type>/<issue-number>-<short-slug>. Create an issue first. Do not
push directly or force-push main. PRs use squash merge and explain the change,
tests, installation impact, state impact, rollback, and secret-scan result.

## Safe checks

    .\scripts\scan-repo.ps1
    .\scripts\validate-git.ps1
    git status --short
    git check-ignore .runtime state config.local.json

Never commit .runtime, state, models, logs, .part files, or
config.local.json. Preserve a bundle, working-tree patch, untracked copy, and
SQLite backup before a history migration.
