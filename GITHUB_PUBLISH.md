# Publishing Terragraft to GitHub

The ZIP contains the Terragraft **source**, not the generated `.env`, encryption key, local database, Terraform state, or the Windows runner's local settings. Publish **this clean extracted source folder** rather than your live installation.

## Recommended: create a new private repository

1. Install the tools if needed, using Windows PowerShell:
   ```powershell
   winget install --id Git.Git -e
   winget install --id GitHub.cli -e
   ```
2. Open a **new** PowerShell window, sign in with `gh auth login` (follow the interactive prompts).
3. Extract `Terragraft_GitHub_Ready.zip` and `cd` into the `Terragraft` folder.
4. Run:
   ```powershell
   .\PUBLISH-TO-GITHUB.ps1 -Repository 'nightmare-moon/Terragraft'
   ```
   This initializes Git, creates a **private** repository, and pushes the source. Only add `-Visibility public` after reviewing the source and deciding to share it publicly.
5. Visit `https://github.com/nightmare-moon/Terragraft` and confirm the files and GitHub Actions status.

## Publish to an existing repository

**Do not run the new-repository helper against an existing repository.** Decide whether to add Terragraft in its own folder or replace the entire repository content; these are different operations. For an existing repository, use a dedicated branch / pull request to avoid overwriting unrelated code.

## Before pushing changes later

- Keep `.env` secret. Never commit it, even to a private repository.
- Avoid committing real infrastructure `*.tfstate`, `*.tfvars`, plan files, or backup dumps.
- A `.gitignore` does **not** remove credentials committed in an earlier commit. Rotate/revoke any exposed tokens and rewrite history if this happened.
- This is a local development lab, **not yet a production-ready shared state service** or fine-grained concurrent Terraform executor.

## Ordinary Git updates after initial publish

```powershell
git status
git add .
git commit -m 'Describe your changes'
git push
```

This GitHub-ready package is meant for source control. Keep your installed Terragraft runtime separately in `D:\tools\Terragraft`.
