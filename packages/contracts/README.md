# API contracts

The v1 study-analysis response is shared between the API and frontend workstreams:

- TypeScript types: [`src/radar-api.ts`](src/radar-api.ts)
- Contract detail and example payload: [`docs/api-contract-v1.md`](../../docs/api-contract-v1.md)
- Runtime validation and JSON Schema: `apps/api/src/radar_api/contracts.py` and
  `GET /v1/contracts/study-analysis`

Keep breaking changes versioned and link schema changes to the relevant Jira issue and pull
request. The contract is for research prototyping only, not clinical use.
