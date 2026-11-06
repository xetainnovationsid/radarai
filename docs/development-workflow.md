# Development workflow

## Branches and pull requests

Create a short-lived `feat/`, `fix/`, or `docs/` branch from `main`. Open a pull request for every change, include the Jira key, and wait for CI and a reviewer before merging.

In GitHub repository settings, protect `main` by requiring pull requests, at least one approval, and the `Web lint and typecheck` and `API lint and tests` checks. Disable force pushes and branch deletion. These settings must be applied by a repository administrator; the current GitHub connection did not expose the linked repository.

## Data and credentials

Keep credentials in local environment files or the hosting secret store. Never commit `.env`, patient data, DICOM studies, model weights, or generated datasets. Use synthetic or explicitly approved anonymized fixtures only.

## Jira

Track implementation work under project **RDA** and reference the relevant issue key in branch/PR context. Setup baseline: [RDA-8](https://iqbaldovandraa.atlassian.net/browse/RDA-8).
