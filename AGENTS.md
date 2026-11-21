<!-- odoo-nix:begin agents -->

## Checks before you push

CI runs the same gates you can run here, and a push that fails one is sent back. Run
them while you work, not after CI fails.

1. **Use the repository's shell.** `direnv allow`, or `nix develop --no-pure-eval`,
   links the locked tools (`tools/.venv`, `tools/.bin`, `node_modules`) and installs the
   git hooks. In a fresh clone or worktree nothing is installed yet: Claude Code's
   `SessionStart` hook installs the git hooks, and other agents should run
   `nix develop --no-pure-eval .#odoo-nix-lint -c prek install -c .pre-commit-config.yaml --hook-type pre-commit --hook-type commit-msg`
   once.
2. **After editing files**, run the hooks on them:
   `prek run -c .pre-commit-config.yaml --files <the files you changed>`. Formatters
   rewrite files; read the result, then run it again until it passes. Always pass
   `-c .pre-commit-config.yaml`.
3. **Before every push or pull request**, run CI's lint gate:
   `nix develop --no-pure-eval .#odoo-nix-lint -c odoo-nix gate lint`. It also checks
   that the managed files are in sync, the manifests, the icons and the coverage floor.
4. **When you changed addon code**, run the tests:
   `ODOO_NIX_CI=1 nix develop --no-pure-eval -c odoo-nix gate test`.
5. **Commit messages and pull request titles** are conventional commits:
   `type(scope): subject`. Allowed types and scopes are in `committed.toml`; a scope is
   an addon's folder name. The commit hook checks them; never skip it with
   `--no-verify`.
6. **Do not change versions or changelogs by hand.** release-please owns
   `.release-please-manifest.json`, `CHANGELOG.md` and the version in each
   `__manifest__.py`; its release pull request moves them.

Files that start with `odoo-nix:managed` are generated: change them inside their
`odoo-nix:local` region, or through the profile, then run `odoo-init --sync`
(`odoo-init --check` verifies).

<!-- Sync rewrites everything between the markers; write your own guidance outside them. -->
<!-- odoo-nix:end agents -->
