# Release process

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
romyq --version   # must print romyq 0.2.0
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

- [ ] Version bumped in `pyproject.toml`
- [ ] `git status` is clean
- [ ] `romyq doctor` passes
- [ ] `python -m build` succeeds
- [ ] Local wheel installs and `romyq --version` is correct
- [ ] (Optional) TestPyPI upload verified
- [ ] `twine upload dist/*` completed without errors
- [ ] `git tag v<version>` pushed
