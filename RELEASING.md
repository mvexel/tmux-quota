# Publishing a release

PyPI uses Trusted Publishing from `.github/workflows/publish.yml` in
`mvexel/tmux-quota`, with the GitHub environment `pypi`. No PyPI API token is
stored in GitHub. The environment is created when the publish job references it
if it does not already exist. Configure environment restrictions in repository
settings as appropriate for your maintainers.

1. Update the versions in `pyproject.toml` and `src/tmux_quota/__init__.py` together.
2. Commit the release as `Release vX.Y.Z` (that exact first line) and push to
   `main`. The commit must change `pyproject.toml` or the publish workflow.
3. Watch the **Publish to PyPI** workflow. It checks the requested version, runs
   the tests on Linux and macOS, builds and validates distributions, and publishes
   through PyPI's trusted publisher.
4. The workflow installs that exact version from PyPI in a fresh environment.
   After verification succeeds it creates the matching GitHub release and tag,
   with the wheel and source distribution attached.

Alternatively, dispatch the workflow from `main` in GitHub Actions with the
expected package version, or publish a GitHub release whose tag matches the
package version. An externally created release runs the same checks and PyPI
upload; the final step leaves the existing GitHub release in place.

Re-running an already published version will be rejected by PyPI. If publication
worked but verification or GitHub release creation failed, rerun only the failed
jobs; do not rerun the successful upload. Publishing the GitHub release with
`GITHUB_TOKEN` does not trigger another release workflow run.

For the first release, register a pending publisher in your PyPI account with
project `tmux-quota`, owner `mvexel`, repository `tmux-quota`, workflow
`publish.yml`, and environment `pypi`. A pending publisher does not reserve the
package name. Future releases use the normal publisher created on first upload.

## Local checks

```sh
uv run --python 3.13 python -m unittest discover -s tests -v
uv build --out-dir release-dist
uvx twine check --strict release-dist/*
```

Use a fresh output directory for each release so older local artifacts are not
uploaded accidentally. Verify from the public index after a successful release:

```sh
uvx --from tmux-quota==X.Y.Z tmux-quota --version
```
