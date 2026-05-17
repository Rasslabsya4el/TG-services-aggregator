# n8n Fixtures

Tracked workflow-facing fixtures live here.

- `requests/` stores secret-free request bodies for the current accepted intake contract.
- Keep fixtures minimal and reproducible. Do not add runtime headers, cookies, execution metadata, or shared runtime paths.
- Naming follows `<contract_version>_<scenario>.request.json`.
