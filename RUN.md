# Kelp AI MVP

This repository contains the web MVP for Kelp AI, a consumer AI agent platform.

## Project Setup

1.  **Install dependencies:**
    ```bash
    npm ci
    ```
2.  **Run the development server:**
    ```bash
    npm run dev
    ```
3.  **Build for production:**
    ```bash
    npm run build
    ```
4.  **Preview production build:**
    ```bash
    npm run preview
    ```
5.  **Generate screenshots:**
    ```bash
    npm run screenshots
    ```

## Deliverables

-   **Working local MVP:** Runs without external keys, demonstrates core features.
-   **Screenshots:** 7 PNGs in `./screenshots/` matching the specified filenames.
-   **RUN.md:** Contains setup and screenshot generation commands.
-   **Summary:** Brief overview of built features and stubs.

## Features & Stubs

-   **Core Functionality:**
    -   Plain-English intent to YAML agent definition generation & preview.
    -   Permission-gated execution model with scopes, risk labels, and revoke functionality.
    -   JSON-driven "Gen UI" renderer for dynamic UIs.
    -   3 demo flows (email triage, web search, reminders) rendered as UI cards.
    -   Screenshot harness using Playwright.
-   **UI Components:** TextBubble, InfoCard, ListCard, ActionCard, InputBar, PermissionRequest, SettingsModal.
-   **Development Stack:** Vite + React.
-   **Mock Data:** Used for Gmail, search, and reminders.
