# Security Policy

## Threat Model & Desktop Automation Safety

`emiliano` is an autonomous desktop coworker and meta-harness capable of synthesizing mouse movements, keyboard strokes, and spawning child terminal processes. Because it operates directly on host desktop environments, security and safety are foundational design principles.

### Key Safety Invariants

1. **Physical Emergency Kill Switch**:
   - The desktop environment registers a global hardware hotkey (<kbd>Esc</kbd>) that immediately terminates active mouse/keyboard synthesis and halts background sub-agent execution.
2. **Local-First & Data Sovereignty**:
   - By default, screen captures and accessibility trees are inspected locally.
   - When using local runtimes (e.g., Ollama), no screen frames or context tokens leave your workstation.
3. **Loopback Binding**:
   - The engine IPC server binds exclusively to `127.0.0.1` (loopback interface) and is protected by a single-instance port mutex. It is never exposed over public network interfaces.
4. **Prompt Injection & Computer-Use Hazards**:
   - When using autonomous screen manipulation, untrusted content (e.g., viewing an untrusted webpage or phishing email) could attempt indirect prompt injection to trigger malicious UI actions.
   - Users are advised to run high-stakes or untrusted autonomous browsing tasks within isolated virtual machines or containers.

---

## Reporting a Vulnerability

If you discover a security vulnerability within `emiliano`, please do **not** open a public issue.

Instead, please send a responsible disclosure report to the maintainers via email at:
**security@emiliano.ai** (or contact the project lead on GitHub via Private Vulnerability Reporting).

Please include:
- A description of the vulnerability.
- Steps to reproduce or proof-of-concept script.
- Potential impact and recommended mitigations.

We will acknowledge receipt within 48 hours and work with you to patch and disclose the issue responsibly.
