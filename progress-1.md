# Transition from CLI to Web Interface

## Previous State
The project functioned as a CLI tool where interactions were synchronous and blocking.
- **Input/Output:** `input()` and `print()` were used directly.
- **Control Flow:** The agent requested human approval synchronously in the terminal, blocking further execution.

## Current Plan
We are transitioning to a client-server architecture to enable a web-based experience.
- **Backend:** Moving to `FastAPI` to expose API endpoints for chat and refund management.
- **Frontend:** Implementing a lightweight, plain `HTML/JavaScript` interface for accessibility.
- **Architecture:** Decoupling agent logic from terminal I/O to handle requests and human-in-the-loop approvals asynchronously.
