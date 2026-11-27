# GitAppho Studio — Charm integration preview

A native Go terminal frontend using Bubble Tea, Lip Gloss and Bubbles, with the existing Python v7.0.1 engine unchanged. The dashboard reads local status and commit history asynchronously through a read-only JSON bridge. All 42 routes are discovered from the engine's registry. Search by intent or Git terminology with Ctrl+P. Tab cycles Home, History and Search; F5 refreshes. Enter opens a guarded workflow in the existing terminal interface. Exit that workflow with 0/Esc to return to Studio. The engine retains confirmations, session locking, network timeouts and secret scanning. No shell-generated Git commands are used by the Go frontend.

## Local installation

Install Go (macOS: `brew install go`), then run the provided Python installer from any directory. It first builds the frontend using the Go module proxy and checksum verification. Only after a successful build does it add Studio source to `~/GitAppho/studio`, install the local binary/bridge and append a zsh dispatcher. It refuses unexpected existing files and mismatched v7.0.1 engines. It does not alter the core, registry, journals, Git history or remote.

Open a new terminal or `source ~/.zshrc`. `gitappho` launches Studio in an interactive terminal; `gitappho classic` starts the original UI; `gitappho save` and other direct commands remain unchanged. `gitappho studio` explicitly opens Studio. The source directory can be committed after reviewing it. The compiled binary lives outside the repository.

## Limits

This is a frontend integration preview, not a full native workflow migration. Interactive workflows still temporarily return to the original terminal UI. Read-only snapshot uses a background worker; mutation handlers use Bubble Tea ExecProcess and temporarily suspend the TUI. No full-screen native progress or conflict editing yet. UI state is not an authority for Git operations. Remote status is unverified until checked by the engine. The installer requires the exact v7.0.1 core from the previous hotfix. Go dependency download/build and interactive rendering must be validated on the user's Mac because the authoring environment has no access to the Go proxy. Six bridge tests passed against disposable local repositories. No live GitHub writes were performed.
