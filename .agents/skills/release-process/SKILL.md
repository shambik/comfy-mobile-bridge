# Release process

## Trigger

Use this skill when preparing a release, changing version files, creating a
tag, updating the changelog, or changing Release Please automation.

## Version rules

- fix and perf: patch.
- feat: minor.
- ! or BREAKING CHANGE: major.
- docs, test, ci, and chore: no release.

Release Please reads Conventional Commits after PRs are squash-merged into
main. It opens or updates a release PR with package.json, package-lock.json,
and CHANGELOG.md. Merging that PR creates the vX.Y.Z tag, GitHub Release, and
notes.

The first clean repository release is v0.1.0. Do not publish a release from
dirty state or claim that a tag is pushed until both the tag and GitHub Release
are verified.

## Required checks

    npm ci
    npm run build
    python -m unittest discover -s tests -p "test_*.py"
    .\scripts\scan-repo.ps1
    .\scripts\validate-manifests.ps1
    .\scripts\validate-git.ps1

Keep model files, runtime state, and user configuration outside the release
artifact.
