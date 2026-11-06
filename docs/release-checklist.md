# Release and submission checklist

This list distinguishes checks completed locally from items that require project-owner inputs or
external access. Do not claim a submission or deployment until the corresponding evidence is linked.

## Engineering and repository

- [x] API contract and migration documented.
- [x] Automated API suite, web lint, web typecheck, and DICOM integration verification run locally.
- [x] Model limitations and non-clinical use documented in the model card.
- [x] Backend container and local PostgreSQL Compose configuration provided.
- [ ] Review and merge the engineering branch through a pull request.
- [ ] Select and add a repository software license. No code license is currently provided.
- [ ] Re-check third-party code and model licenses before redistribution.

## Deployment and model evidence

- [ ] Configure Firebase project settings, production domain, TLS, and allowed web origins.
- [ ] Choose a deployment host; provision database, storage, backups, and monitoring.
- [ ] Provision a compatible research checkpoint and attach its provenance and validation evidence.
- [ ] Configure a server-side Meta Model API key and confirm the account's model access.
- [ ] Record deployed API and frontend URLs and confirm `/health/ready` from the deployment.
- [ ] Run an end-to-end upload, inference job, human correction/review, and report-draft walkthrough
  using only synthetic or properly de-identified data.

## Submission

- [ ] Verify the official event deadline, eligibility, attribution, reuse, and format requirements.
- [ ] Produce a concise demo using synthetic data and show failure recovery and model limitations.
- [ ] Verify repository, build, deck, demo video, and all portal fields with a second team member.
- [ ] Save the submission receipt and final artifact links in the project handoff.
