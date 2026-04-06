Required Document Description: Business Logic Questions Log:

HTMX Authentication and HMAC Signatures
Question: The prompt specifies that APIs require HMAC-SHA256 request signing with a timestamp skew limit and nonce anti-replay, while also stating the UI is built with server-rendered pages enhanced by HTMX. It's unclear if HTMX browser requests must implement HMAC signing or if they should rely solely on the short-lived JWTs.
My Understanding: Browser-based HTMX requests natively are not designed to perform complex cryptographic hashing. HMAC is typically intended for machine-to-machine integrations.
Solution: Apply JWT-based session authentication for all browser/HTMX requests, and enforce HMAC-SHA256 signatures exclusively on external REST API endpoints.

Pricing and Inventory Rules Engine vs. Retail vs. Venues
Question: The prompt is titled "Sports Venue Commerce & Knowledge Hub" and mentions a "pricing and inventory rules engine" with "minimum booking length (default 60 minutes)" and "advance-booking windows". However, the primary management objects described are retail catalogs and perishable inventory. Are users renting sports equipment/spaces (hence "booking length"), or just purchasing retail items?
My Understanding: The terminology "booking length" and "advance-booking windows" strongly implies equipment rentals or venue facility reservations, rather than pure retail purchases where inventory permanently leaves.
Solution: Implement a unified inventory model where items can be flagged as "Rentable" (using booking lengths and date-range rate plans) or "Purchasable" (straight retail), applying the rules engine accordingly.

Inventory Variance Workflow
Question: The prompt states that "stock counts record variances and require a reason note when variance exceeds 2% or 10 units." It did not specify the workflow after the note is provided—does it require administrator approval, or does it automatically adjust stock levels?
My Understanding: Given the offline-first nature and the role of Inventory Manager, providing the note is sufficient to proceed with the stock adjustment, but it must be logged in the audit trail for Administrator review.
Solution: Allow the Inventory Manager to finalize the count once the mandatory note is provided, automatically generating a variance adjustment and an audit log entry labeled "High Variance Count".

Order Locking Confirmation
Question: The prompt specifies "order locking with a 20-minute hold that auto-releases if not confirmed," but there is no mention of a payment processor. What constitutes an order "confirmation" in an offline-first system?
My Understanding: Confirmation is an operational status change (e.g., staff marking the item as checked out/paid physically at the counter), not necessarily an online payment confirmation.
Solution: Add an operational transition action in the UI allowing Staff Users to mark a "held" order as "confirmed/completed" or "cancelled" manually, without requiring any external payment integration.

Competency Assessments Grading
Question: The prompt states "Trainer who assembles and grades assessments; regular Staff Users can search, reserve, and complete assigned tests." It does not specify if the assessments are automated multiple-choice or require manual grading.
My Understanding: Since the Trainer explicitly "grades assessments", it implies there are free-text answers or subjective components that cannot be entirely auto-graded, or at least a mix of auto- and manual-graded items.
Solution: Design the assessment data model to support both auto-gradable questions (multiple choice) and manual-grading required questions (short answer). Completing a test sets its status to "Awaiting Grading" for a Trainer to review.

Overbooking Guard Buffer
Question: The prompt mentions an "overbooking guard that rejects holds once a configurable buffer is exceeded". How does a configurable buffer map to tangible inventory? 
My Understanding: The buffer acts as a safety margin (e.g., allowing holds up to 105% of stock capacity) if natural attrition/cancellation is expected.
Solution: Add an overbooking percentage modifier setting to inventory items or categories to allow holds slightly beyond available stock, up to that dynamic ceiling.
