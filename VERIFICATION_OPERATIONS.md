# Seller Verification Centre operations

## Before collecting personal documents

The Verification Centre can be opened by farmers and can accept privacy requests. Evidence intake and preview fail closed until an encrypted external vault, privacy settings, and HTTPS are configured. Do not use real identity records in the development or demonstration environment.

| Process environment variable | Requirement |
|---|---|
| `HARVEST_KYC_PRIVATE_DIR` | Absolute path to an existing directory outside the application, static files and produce-photo storage. Restrict OS access to the service identity and authorised custodians. |
| `HARVEST_KYC_ENCRYPTION_KEY` | Dedicated Fernet key from a secret manager, separate from Flask and payment secrets. Generate via the installed cryptography library. Keep a recoverable rotation plan under restricted access. |
| `HARVEST_KYC_REVIEWERS` | Comma-separated administrator account email addresses authorised to review evidence. |
| `HARVEST_KYC_CONTROLLER` | Actual responsible party name to show in the privacy notice. |
| `HARVEST_KYC_PRIVACY_CONTACT` | Approved information officer or privacy contact. |
| `HARVEST_KYC_BASIS` | Approved basis from `contract` or `legitimate_interest`. Have the responsible party document applicability and any balancing assessment before rollout. The acknowledgement box records notice delivery, not consent. |

Use HTTPS with secure cookies and appropriate proxy handling. Do not trust forwarded scheme headers from arbitrary clients. Non-synthetic collection also requires an approved privacy notice, retention schedule and rights response process. Confirm Section 18 disclosures, the applicable Section 11 justification, storage location, staff permissions, backup controls and an incident process. [Protection of Personal Information Act](https://www.treasury.gov.za/POPIA/POPI%20Act%204%20of%202013.pdf)

## Evidence and decisions

- Accept up to two still JPEG or PNG images, at most 2 MB each. The service decodes pixels and re-encodes them, dropping original metadata and appended bytes. PDF and video intake are disabled. Use letter or certificate images where appropriate, or an assisted in-person review. Only an allowlisted reviewer may record decisions or access another user’s submitted evidence. Malware scanning for raw files is unavailable.
- The identity route supports SA ID, passport, certified copies and assisted original-document review. Match the account name and independently assess authenticity. Proof of legal ownership is unnecessary where the grower has a legitimate right to work the land or source the produce.
- Identity, farming/supply and batch status are separate. Both required seller checks must be current for a seller badge. Existing administratively approved sellers retain legacy access and gain no new badge on migration. Managed approvals lose public eligibility on evidence expiry, suspension or changes to the stored name/village. Offer acceptance, supply matching, marketplace, detail pages and public photo access use effective eligibility.
- Verify batch stock using independently corroborated inventory, weighing or inspection. Grade publishing requires the reviewer to confirm an independently supported same-lot class, issuer, reference and expiry. The supported grade mapping covers potatoes. Extend it only after a commodity-specific review. [South African potato grading regulations](https://www.gov.za/sites/default/files/gcis_document/201903/42260rg10916gon273.pdf)
- Keep document identifiers and private locations out of audit reasons. Review decisions, access and rights-request handling are recorded. The audit has application-level append-only SQLite triggers. System operators with database privileges require external audit and access controls.
- Encrypted evidence is accessible for up to 90 days from submission. Schedule `flask --app app purge-verification-evidence --apply` after reviewing the default dry run. For an authorised earlier deletion, use the targeted dry run with `--case-id CASE_ID`, then apply it after reviewing the case and documenting the rights request. Files are stored separately from regular SQLite and produce-photo backups. Protect any separately approved encrypted backup with its own access and deletion schedule. Avoid permanent vault snapshots.
- The privacy request workflow records access, correction, deletion and objection. A reviewer records completion after verifying the requester, assessing any lawful retention exception, and taking the appropriate action. Do not email raw ID images or export them into spreadsheets. Legal holds, verified identity requests and response deadlines require an operating procedure.
- The Centre uses the site translation catalogues for navigation, state and badge labels. The critical legal notice and review instructions remain in English until reviewed translations can be approved.
