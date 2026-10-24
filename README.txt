LEAD INTAKE: CTA ATTRIBUTION AND FAILURE HANDLING
Independent local demonstration prepared by Oleksii, 24 October 2026.
Based on the public Bogmar BB brief (Useme 146392).
This is a proposal sample, not work commissioned or endorsed by Bogmar BB.

Run: python3 -m unittest -v
Requirements: Python 3.9+ standard library. No installation, credentials or network.

What actually runs:
- Save a synthetic enquiry to SQLite before downstream processing.
- Retain the page, individual CTA identifier and five named UTM fields.
- A repeated request ID does not create a second record; changed content with
  the same ID is rejected for explicit reconciliation.
- Missing message text, low confidence, invalid model output or model failure
  goes to a manual-review queue with the enquiry preserved.
- A fixed category-to-queue map prevents model output choosing arbitrary recipients.
- A durable outbox retains failed notification attempts for retry.
- Restart and simulated failures are covered by executable tests.

What is simulated:
The classifier and notification transport are test doubles. No real model,
n8n instance, email inbox or company form is connected. Routing categories and
queue names are illustrative; they are not Bogmar's internal organisation.
Only artificial contact data is used. This does not measure AI classification accuracy.

Production implementation still needs:
1. Agreed form payload and CTA identifiers from the website developer.
2. Server-side authentication, spam controls, input limits and acknowledgement policy.
3. n8n integration, approved model and mailbox credentials in the client's environment.
4. Accepted category labels and routing rules, including forms without message text.
5. PostgreSQL or equivalent durable storage, backups, retention and failure alerts.
6. Tested notification idempotency. Plain SMTP cannot guarantee exactly-once delivery
   after an ambiguous timeout. This sample assumes an idempotent sender.
7. Concurrency/locking and retry backoff; this local sample uses one worker.
8. Realistic data-volume and privacy review before handling actual enquiries.

The paid pilot offered separately covers one form, two CTA identifiers and up to
three agreed categories. Demonstration code is supplied under the MIT licence.
