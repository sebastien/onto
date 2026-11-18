# Publishing onto-lang

You need Python 3.14 or later, uv, and a PyPI account with permission to
publish `onto-lang`.

For the first release, use the version already in `pyproject.toml`. For
later releases, update it before publishing, for example:

```sh
uv version --bump patch
```

Review and commit the source changes, `pyproject.toml`, and `uv.lock`.
PyPI does not let you replace an existing release file.

To build the source distribution and wheel without uploading:

```sh
make test-release
```

The artifacts are written to `dist/`. This target also installs the wheel into
a temporary environment and checks both CLI entry points outside the checkout.
Set `UV_PYTHON=3.14` to check the minimum supported Python version.

`make test-hexa` requires the hexa integration to be importable before running
the suite, so its tests cannot silently skip. It looks in `../hexa/src/py` by
default; override that with `HEXA_SRC=/path/to/hexa/src/py`.

To run the suite including hexa, rebuild, and publish the current version to
PyPI:

```sh
read -r -s -p 'PyPI token: ' UV_PUBLISH_TOKEN; echo
export UV_PUBLISH_TOKEN
make release
unset UV_PUBLISH_TOKEN
```

The token prompt uses Bash and keeps the token out of shell history. For a
new project, create an account-wide token on PyPI; after the first upload,
replace it with a token scoped to `onto-lang`.

`make release` uploads only the two artifacts for the current version, not
older versions left in `dist/`. It does not commit, tag, or push Git changes.

See the [uv publishing guide](https://docs.astral.sh/uv/guides/package/)
for token authentication and trusted publishing.
