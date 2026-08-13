# Clean history migration

Before an orphan history migration:

    git bundle create backup.bundle --all
    git diff > working-tree.patch
    git ls-files --others --exclude-standard
    Copy-Item state\jobs.sqlite3 backup\jobs.sqlite3

Create a local backup branch before replacing main. Run the personal-data scan
on the final tracked tree, check all ignored paths, and inspect the first
commit before pushing. Keep the old bundle and branch outside the published
history.
