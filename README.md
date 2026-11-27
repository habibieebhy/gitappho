# GitAppho v5 — Git without the complexity

One terminal command opens a contextual menu for Git and GitHub. Use intent, not memorized Git commands.

## Upgrade on macOS

Requires Python 3.9+, Git 2.38+ (for rebase safeguards), GitHub CLI for remote operations and Gitleaks 8.x with the modern `git` subcommand for outgoing commit scans. Install dependencies with `brew install gh gitleaks` if missing. Run `python3 ~/Downloads/install_gitappho_v5.py` on the existing `~/GitAppho` project; then `source ~/.zshrc` and `gitappho --doctor`. Restart existing IDE terminals. The installer preserves the project registry and creates backups under `~/.config/gitappho/`. It writes source and installed application files, but does not run Git, publish anything, or modify GitHub credentials. Existing VS Code user keybindings are not changed. Use the existing Control+Option+Shift+G keybinding only at an idle integrated terminal prompt in the exact project root. Disable conflicting Apple Shortcuts keystroke injection.

## Everyday operations

`gitappho` adapts to whether the directory has an independent Git repository, a verified remote, a registered account, or an interrupted Git operation. New projects can be published with separate selection, commit and push confirmations; private is the default. Existing projects are never silently initialized or overwritten. Connect to an empty remote or a compatible existing history; clone unrelated remote content into a separate new folder. All network operations use an approved HTTPS GitHub remote and account and validate the repository identity. `--login`, `--accounts`, `--projects`, `--register`, `--account USERNAME`, `--publish`, `--connect`, `--status`, `--doctor`, `--version`, and `--advanced` are available. Accounts are selected per project; commit author identity is separate.

Normal menu: save and publish, push existing commits, fast-forward updates, branch management, pull requests, change account, recover/revert, local commit, compare with GitHub, advanced Git & recovery tools. Save/publish and push exit after success; clean projects no longer ask to stage. Branch management includes local and reviewed remote merges, local branch creation/switching/comparison/deletion and remote branch download/publication.

## Advanced tools (main menu 10 or `gitappho --advanced`)

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
