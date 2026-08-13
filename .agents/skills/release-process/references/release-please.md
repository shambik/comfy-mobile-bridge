# Release Please configuration

The repository keeps:

- release-please-config.json
- .release-please-manifest.json
- .github/workflows/release-please.yml

The workflow uses GitHub Actions permissions only for contents, pull requests,
and issues. It does not download models or expose the local bridge.
