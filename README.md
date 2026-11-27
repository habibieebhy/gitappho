# GitAppho v4 — Git without the complexity

One keyboard shortcut opens a context-aware terminal menu for Git and GitHub.

## Install and activate

Requires Python 3.9+, Git 2.28+, GitHub CLI (`brew install gh`) for network operations, and an interactive local zsh terminal. Run the standalone `install_gitappho_v4.py` installer on the Mac with the existing `~/GitAppho` source folder. It backs up existing files and updates the source and the per-user executable at `~/.config/gitappho/gitappho.py`. No Git initialization, commit, staging or remote operation occurs during installation. Existing project registrations are retained. Restart all old terminals and disable the Apple Shortcuts hotkey (old keystroke-injection method). The native VS Code keybinding in `vscode/keybindings.json` sends `gitappho` and Enter; merge it into user keybindings if not already set. Use Control+Option+Shift+G only at an idle terminal prompt, from the intended project root.

## Start

- `gitappho --doctor` checks dependencies.
- `gitappho --login` uses GitHub CLI's browser login. Repeat to add accounts.
- `gitappho --accounts` lists saved logins (GitHub CLI handles credentials).
- `gitappho` opens the menu and detects your repository's state.
- `gitappho --publish`, `--connect`, `--register`, `--account USERNAME`, `--projects`, `--status` and `--help` are direct shortcuts to common operations.

If no independent repository exists, the menu offers publication or connection. Publishing asks for the account, exact folder, repository name and visibility (private by default), then confirms creation, lets you select untracked files explicitly, stages and commits after review, creates an empty remote, registers it and asks separately before pushing. It never assumes a failed lookup means a repo is absent; GitHub's create operation determines whether the name is available. Existing populated remotes with no compatible local history can be cloned into a new sibling directory rather than overwritten. An existing local repository with compatible history can be connected. Registration pins the exact remote, GitHub ID and login. Accounts are selected per project without changing the CLI's active account globally. Git author name/email are separate.

## Existing projects

- Save and publish: preview status, select new files by number (or ALL after reviewing the displayed list), confirm STAGE, inspect staged summary/diff, enter message and COMMIT, review outgoing commits/files and confirm PUSH. Tracked modifications and deletions are included; untracked files are never silently staged. Explicitly staged files are also included.
- Push existing commits, local commit only, fast-forward synchronization, remote comparison.
- Branches: create from a local base, switch local branches, download remote branches, compare, merge locally with separate merge and commit approvals, delete a merged local branch, publish current branch.
- Pull requests: create, list, merge a ready same-repo PR using GitHub's normal checks and head-commit matching; no admin bypass.
- Recovery: abort a merge/revert, or revert the latest ordinary commit by making a new commit. No hard reset or force push.

## Safety and limitations

Requires an exact independent project root inside the user's home; blocks home, broad personal directories, personal-folder subtrees, parent repos, linked worktrees, shallow repos and several unusual Git configurations. Only one explicit HTTPS github.com origin is supported (no SSH, enterprise or credential-bearing URLs). Remote redirects and changed IDs are blocked. Creation is limited to the selected personal account; organization repositories can be created on GitHub and connected. Local work must be clean to switch, merge or fast-forward. A merge conflict stops for manual IDE resolution or abort; no automatic conflict resolution. No remote branch deletion, history rewriting or automatic rebase. Remote operations honor repository permissions and rules; PR merge method availability depends on GitHub. Sensitive-name blocking is intentionally strict (including `.env.example` and names containing `secret`); it is not a content secret scanner. Review actual diffs and existing history. Only run in trusted repositories; existing Git hooks and filters configured outside this application may execute as normal (custom configured filters are blocked). GitAppho is not a sandbox. New-file selection and outgoing filename review are capped at 500, and selected new files at 20 MiB each. Large projects require manual selective staging; the outgoing review cap still applies. Cancellation can leave a local repo, staged changes, local commit or empty remote depending on the stage; inspect status and resume without forcing. No credentials are stored in project source or registry. Keep registry and installer backups outside repositories.

## Tests

`cd shell && python3 -m unittest -v test_gitappho` runs isolated local Git regression tests. Network pushes in tests use a temporary local bare repository with simulated GitHub identity; live GitHub API, macOS keybinding and browser sign-in require verification on the actual Mac.
