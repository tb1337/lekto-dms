## Summary

<!-- What changes and why; link the issue (`Closes #…`). -->

## Release notes

<!-- One sentence for the user: what changes for them. It stands under the title in the release
notes. Leave the section empty for maintenance, CI and refactoring. -->

## Checks

- [ ] Backend: `ruff check`, `ruff format --check`, `mypy`, `lint-imports`, `pytest`
- [ ] Web UI (if `web/` changed): `pnpm lint`, `format:check`, `check`, `test`, `build`
- [ ] Migration client (if `migration/` changed): its checks
- [ ] The UI follows [`web/DESIGN.md`](../web/DESIGN.md); a change it does not cover, or a
      deviation, changes `web/DESIGN.md` in this pull request
- [ ] Exactly one category label from `.github/labels.yml`
