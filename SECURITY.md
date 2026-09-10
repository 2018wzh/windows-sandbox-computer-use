# Security Policy

## Supported versions

Only the latest tagged release is supported. Upgrade before reporting behavior already corrected on the default branch.

## Reporting a vulnerability

Use GitHub private vulnerability reporting for issues that could:

- expose a host directory beyond the explicitly selected root;
- escape a Windows Sandbox boundary;
- leak credentials, Sandbox identifiers, local paths, screenshots, or logs;
- inject untrusted visual content into control instructions;
- bypass confirmation or authorization boundaries;
- enable generic RDP access, unauthorized host command execution, or certificate validation bypasses.

Do not include live credentials, private screenshots, host paths, or confidential debug artifacts in a public issue. For ordinary bugs that do not expose security-sensitive information, open a GitHub issue with bounded adapter output and dependency versions.

## Security boundaries

- The skill operates only an authorized Windows Sandbox.
- Directory sharing is read-only unless `--allow-write` is explicitly selected.
- The adapter rejects host filesystem roots and path traversal.
- The repository does not bundle IronRDP Agent or Windows Sandbox binaries.
- The adapter does not expose passwords, generic RDP targets, certificate bypasses, clipboard redirection or whole-volume redirection.
- Authorized guest commands use native wsb exec. They can modify guest state and explicitly writable shares. The default context is ExistingLogin; System is explicit. No guest command is evaluated by a host shell.
