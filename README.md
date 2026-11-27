# GitAppho v7 — Graph-first session engine

**Know what you want. Not what to type.**

Run `gitappho` for five primary intentions, plus a searchable action palette. Use arrows or numbered input. Recoverable errors return to the home screen; confirmation verbs accept either case, and invalid confirmations reprompt. Type CANCEL to cancel. Select 0/Esc at home to exit. The journal is local and never automatically replays operations. A project lock prevents overlapping v7 interactive sessions; it does not prevent external Git writes. Legacy direct flags are still one-shot. macOS/Linux only for persistent sessions; Windows untested.

```sh
gitappho --version
gitappho --graph-check
gitappho
gitappho find stash pop
gitappho find branch delete
gitappho find remote merge
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for graph design, state constraints, feature coverage, implemented versus planned structures, and limits. 60 local regression tests passed during development; GitHub and scanner responses remain simulated in those tests. No live GitHub operations were performed.

## Upgrade from v6

Run `python3 ~/Downloads/install_gitappho_v7.py`. The installer refuses to replace unexpected core source contents; if your source differs from the supplied v6 or v7, review differences first. Other replaced files are backed up under `~/.config/gitappho/`. No remote operations, staging or publication are performed. Restart terminals, then use `gitappho --version`. Requires Python 3.9+, Git 2.38+, and GitHub CLI / Gitleaks for applicable remote workflows. Existing registry and keyboard shortcuts remain unchanged.

## Inherited v6 workflows and safety details

# GitAppho v6 — Git without the complexity

One terminal command opens a contextual menu for Git and GitHub. Use intent, not memorized Git commands.

## Previous v6 installation notes

Requires Python 3.9+, Git 2.38+ (for rebase safeguards), GitHub CLI for remote operations and Gitleaks 8.x with the modern `git` subcommand for outgoing commit scans. Install dependencies with `brew install gh gitleaks` if missing. Use the v7 installer above on the existing `~/GitAppho` project; then `source ~/.zshrc` and `gitappho --doctor`. Restart existing IDE terminals. The installer preserves the project registry and creates backups under `~/.config/gitappho/`. It writes source and installed application files, but does not run Git, publish anything, or modify GitHub credentials. Existing VS Code user keybindings are not changed. Use the existing Control+Option+Shift+G keybinding only at an idle integrated terminal prompt in the exact project root. Disable conflicting Apple Shortcuts keystroke injection.

## Everyday operations

`gitappho` adapts to whether the directory has an independent Git repository, a verified remote, a registered account, or an interrupted Git operation. New projects can be published with separate selection, commit and push confirmations; private is the default. Existing projects are never silently initialized or overwritten. Connect to an empty remote or a compatible existing history; clone unrelated remote content into a separate new folder. All network operations use an approved HTTPS GitHub remote and account and validate the repository identity. `--login`, `--accounts`, `--projects`, `--register`, `--account USERNAME`, `--publish`, `--connect`, `--status`, `--doctor`, `--version`, and `--advanced` are available. Accounts are selected per project; commit author identity is separate.

## Five intentions

```sh
gitappho save
gitappho update
gitappho new checkout-page
gitappho combine
gitappho fix
```

Run `gitappho` to see the five-action menu. On POSIX interactive terminals use Up/Down, Enter, or Esc; numbers also work. Set `GITAPPHO_PLAIN=1` to use numbered input. Legacy advanced submenus remain numbered. Exact supported phrases include `gitappho "save my work"`, `gitappho "undo my last commit but keep my code"`, and `gitappho "set my work aside"`. No AI or external language service; unknown phrases are rejected.

- Save: local commit or reviewed upload, and initial publish/connect for new projects. Existing unregistered projects can save locally without authentication; network actions request registration first.
- Update: compare verified remote branch with local commits. Already-current/ahead branches leave files alone. A clean behind-only branch can fast-forward after approval. Tracked-only dirty work can be stashed, fast-forwarded and applied with index restoration; the original stash remains even on success. Untracked files stop this automatic workflow. Ignored files that would be overwritten by fast-forward block the merge. Diverged histories require explicit reviewed merge or guarded private-only rebase; dirty diverged branches must save or set aside work first.
- New: create a branch from current HEAD, explicitly carry unfinished changes, switch, download a verified remote branch or manage saved work.
- Combine: local merge, remote update, pull requests, guarded rebase, cherry-pick or branch comparison.
- Fix: automatically route interrupted operations to recovery, or select undo, restore, rescue, bisect, privacy or connection tools. All original v5 advanced commands remain via `--advanced` or Fix > All advanced tools.

Remote freshness is not inferred from local tracking refs. Authentication and publishing use existing v5 safeguards. In v7, normal interactive sessions return to the main menu after a workflow. Exact project root required.

## Advanced tools (`gitappho --advanced`)

1. Stash tracked staged and unstaged changes. Untracked/ignored files remain. Restore using apply or pop-like apply-then-drop, with original stash retained on failure and a recovery reference on successful drop. Restore requires a clean working tree.
2. Rebase private feature commits onto another local branch, soft undo the last commit, correct the last message, squash 2–20 recent commits. Protected main/master, merge-containing ranges, tagged and currently visible remote-reachable commits are blocked. Existing local tracking refs are checked as well. No force push. Only rewrite work nobody else depends on; remote verification cannot establish whether commits were ever copied or shared elsewhere. Create a local checkpoint before rewriting.
3. Cherry-pick or revert one ordinary commit, restore an unstaged deletion from HEAD, untrack an ignored file without deleting the local copy, view blame. Untracking does not erase history; create the ignore rule yourself first.
4. List checkpoints and reflog; create a new rescue branch from a known commit without resetting the working branch. Checkpoints retain committed trees, not arbitrary unsaved work; successful stash drop retains a stash-object reference.
5. Interactive manual bisect: identify known-good commit, test historical checkouts, mark good/bad/skip, reset to original branch. Clean working tree required.
6. List GitHub issues, CI runs, PR checks and releases. Create a draft release only when a matching tag already exists at the current published commit. Tag creation and release publication remain manual.
7. Scan current HEAD history using Gitleaks.

On conflict, rerun GitAppho (or `--advanced`), choose recovery, inspect index stages, edit manually in your IDE, mark individual files resolved, and continue or abort the supported operation. Never automatically choose a conflict side. Rebase, merge, cherry-pick and revert support continuation; stash conflicts retain the stash and require manual working-tree recovery rather than an unsafe automatic reset. During bisect the recovery menu shows bisect actions. Complex sequencer operations, binary conflicts and some unusual configurations require manual Git. Git hooks may run as usual; only use trusted repositories.

## Safety

Home, broad personal directories, inherited/parent repos, linked worktrees, shared object stores, shallow repositories and unusual Git transport configuration are blocked. New files are explicitly selected; already tracked changes are staged after approval. Sensitive filenames, symlinks and submodules are guarded on commit/push. Outgoing commits are reviewed and must pass Gitleaks before push; findings, missing scanner or scanner error stop the push. Gitleaks uses an explicit default-rules configuration and ignores repo-specific allow markers and ignore files. It is not a guarantee against all secrets (e.g. binary files, novel token formats); review contents and history. The scanner does not upload source. The initial publishing workflow can leave a local commit or an empty remote when a later step is blocked. Public repository creation is explicitly selected. Never store tokens, project registry, backups or server passwords in source control. The tool is not a security sandbox and assumes trusted repositories and local executables. Remote branch deletion, automatic conflict resolution, hard resets, arbitrary interactive rebases, linked worktrees, and force-push remain intentionally unsupported. Existing GitHub restrictions still apply. More than 100 remote refs or 100 rewritten commits require manual review.

## Tests

`cd ~/GitAppho/shell && python3 -m unittest -v test_gitappho` uses disposable local repos. Tests simulate GitHub auth and scanner return codes; real GitHub and Gitleaks integrations still require live testing. `pyproject.toml` provides a standard Python console entry point for subsequent CLI distribution; PyPI/Homebrew publication is not included in this installer.
