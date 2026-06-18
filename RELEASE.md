# Release process

## Automated release (recommended)

Pushing a version tag triggers `.github/workflows/release.yml`, which:

1. Builds standalone binaries with PyInstaller on 4 platforms (Linux x86_64, macOS Intel, macOS ARM64, Windows x86_64)
2. Creates a GitHub Release with all binaries, the wheel, and the sdist attached
3. Publishes to PyPI via trusted publishing (OIDC — no token needed if configured)

### One-time PyPI trusted publisher setup

Before the first automated release, configure a trusted publisher on PyPI:

1. Go to `https://pypi.org/manage/project/romyq/settings/publishing/`
2. Add a trusted publisher:
   - Owner: `adarsh`
   - Repository: `romyq`
   - Workflow: `release.yml`
   - Environment: `pypi`

### Release steps

```bash
# 1. Bump version in pyproject.toml
# 2. Commit
git add pyproject.toml
git commit -m "chore: bump version to 0.2.0"

# 3. Tag and push — this triggers the workflow
git tag v0.2.0
git push origin main v0.2.0
```

The workflow runs automatically. Monitor it at:
`https://github.com/adarsh/romyq/actions`

### Version verification

After the workflow completes:

```bash
pip install romyq==0.2.0 --force-reinstall
romyq --version        # must print: romyq 0.2.0
romyq version          # must show: wheel or sdist (not editable)
python -m romyq --version
```

If you are on an editable install during development, verify the version is not stale:

```bash
romyq version          # check "install" line
# if it shows legacy egg-info, re-run:
pip install -e .
romyq --version
```

---

## Manual release

## Prerequisites

```bash
pip install build twine
```

You need a [PyPI](https://pypi.org) account with a project token for `romyq`,
or an account-scoped token.

## Steps

### 1. Bump the version

Edit the single version field in `pyproject.toml`:

```toml
[project]
version = "0.2.0"
```

Commit:

```bash
git add pyproject.toml
git commit -m "chore: bump version to 0.2.0"
```

### 2. Build

```bash
python -m build
```

This produces two files in `dist/`:

```
dist/romyq-0.2.0.tar.gz
dist/romyq-0.2.0-py3-none-any.whl
```

### 3. Test the build locally

```bash
pip install dist/romyq-0.2.0-py3-none-any.whl --force-reinstall
romyq --version        # must print: romyq 0.2.0
romyq version          # must show: wheel or sdist (not editable)
python -m romyq --version
romyq doctor
```

### 4. Publish to TestPyPI (optional but recommended)

```bash
twine upload --repository testpypi dist/*
```

Install from TestPyPI to verify:

```bash
pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ romyq==0.2.0
romyq --version
romyq doctor
```

### 5. Publish to PyPI

```bash
twine upload dist/*
```

Verify the live release:

```bash
pip install romyq==0.2.0
romyq --version
```

### 6. Tag the release

```bash
git tag v0.2.0
git push origin v0.2.0
```

## Rollback

PyPI does not allow re-uploading a file for an existing version.
Deleted versions leave a gap; use **yank** instead.

### Yank a release (preferred)

Yanking marks a version as broken without removing it. Existing installs
continue to work; `pip install romyq` stops resolving to the yanked version.

1. Go to `https://pypi.org/manage/project/romyq/release/<version>/`
2. Click **Yank release** and provide a reason.

Or with the PyPI API (requires an API token):

```bash
# The UI is easier; the API requires authentication headers.
# Prefer the web interface for yanking.
```

### Publish a patch fix

```bash
# Fix the issue, bump to 0.2.1
# Repeat the build and publish steps above
```

## Credentials

Store your PyPI token in `~/.pypirc`:

```ini
[pypi]
  username = __token__
  password = pypi-...your-token-here...

[testpypi]
  username = __token__
  password = pypi-...your-testpypi-token-here...
```

Or pass via environment variable:

```bash
TWINE_USERNAME=__token__ TWINE_PASSWORD=pypi-... twine upload dist/*
```

## Checklist

- [ ] Version bumped in `pyproject.toml` (single source of truth)
- [ ] `git status` is clean
- [ ] `romyq doctor` passes
- [ ] `python -m build` succeeds
- [ ] Local wheel installs: `romyq --version` prints expected version
- [ ] `romyq version` shows `wheel or sdist` (not `editable` or `0.0.0+unknown`)
- [ ] `python -m romyq --version` matches `romyq --version`
- [ ] (Optional) TestPyPI upload verified
- [ ] `twine upload dist/*` completed without errors (manual) or trusted publisher configured (automated)
- [ ] `git tag v<version>` pushed
- [ ] GitHub Actions workflow completed successfully
- [ ] GitHub Release assets verified (4 binaries + wheel + sdist)
