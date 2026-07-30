# Safrina Mattress Warranty Portal — Backend

The asynchronous API and business-logic service behind the **Safrina Mattress Warranty Portal**.

Built with FastAPI and MongoDB, this service handles passwordless authentication, customer profiles, DBF product imports, admin-reviewed warranty registrations, product traceability, service enquiries, customer feedback, support contacts, and persistent catalogue storage.

[![FastAPI](https://img.shields.io/badge/FastAPI-0.109-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![MongoDB](https://img.shields.io/badge/MongoDB-Motor-47A248?logo=mongodb&logoColor=white)](https://www.mongodb.com/)
[![Render](https://img.shields.io/badge/Deploy-Render-46E3B7?logo=render&logoColor=white)](https://render.com/)

## Core capabilities

- Email OTP delivery through the Brevo transactional email API
- JWT bearer authentication with customer and admin roles
- Profile and mandatory-feedback access guards
- MongoDB Atlas persistence through the asynchronous Motor driver
- Automatic collection index creation and legacy OTP-index repair
- `BOOKSALE.dbf` and `SERIALS.dbf` parsing, joining, normalization, and upsert
- Background import processing with job progress and batch history
- Unique serial/piece ownership and duplicate-registration prevention
- Admin approval or decline of warranty registration requests
- Warranty coverage calculated from the customer's dealer bill date
- Configurable old-stock detection based on dispatch-to-purchase age
- Online-warranty cutoff with manual enquiry handling for older products
- Category-based warranty durations and up to 15 warranty terms
- Customer and admin enquiry workflows
- Per-product customer purchase feedback
- Dealer discovery using imported city data
- Admin-managed customer support contacts
- Persistent PDF e-catalogue storage in MongoDB GridFS
- Confirmed customer deletion with related-data cleanup

## Architecture

```text
React frontend
      │ HTTPS / JSON + JWT
      ▼
FastAPI routes
      │
      ├── Authentication and access guards
      ├── Warranty and eligibility services
      ├── DBF parsing and import pipeline
      └── Catalogue file streaming
      │
      ▼
MongoDB Atlas
      ├── Application collections
      └── GridFS catalogue bucket
```

The **Serial Number / Piece Number** is the system's central business identifier. It links imported inventory, customer ownership, registration requests, approved warranties, enquiries, feedback, and admin traceability.

## Business workflow

1. An admin imports `BOOKSALE.dbf` and `SERIALS.dbf`.
2. The importer joins both sources by `MAIN_KEY` and upserts product pieces.
3. An authenticated customer completes their profile and looks up a piece.
4. The API checks product existence, ownership, registration state, cutoff eligibility, and the active category warranty rule.
5. The customer supplies the dealer invoice number and purchase date, then accepts the applicable warranty terms.
6. A pending registration request is created and per-piece feedback becomes mandatory.
7. An admin reviews buyer, dealer, distributor, product, dealer-invoice, and company-dispatch details.
8. Approval creates one uniquely owned registered product and calculates its warranty period from the customer purchase date.

Company dispatch invoice fields imported from DBF data are admin-only traceability information. They are never presented to customers as their purchase invoice.

## Tech stack

| Area | Technology |
| --- | --- |
| API framework | FastAPI |
| ASGI server | Uvicorn |
| Database | MongoDB / MongoDB Atlas |
| Async database driver | Motor |
| Validation and settings | Pydantic |
| Authentication | JWT with `python-jose` |
| Transactional email | Brevo API via HTTPX |
| DBF parsing | dbfread |
| File uploads | python-multipart |
| Catalogue storage | MongoDB GridFS |
| Hosting | Render |

## Project structure

```text
.
├── main.py                 # FastAPI application and route registration
├── config.py               # Environment-backed settings
├── database.py             # MongoDB lifecycle, indexes, and GridFS access
├── schemas.py              # Request and response validation
├── middleware/
│   └── auth_guard.py       # JWT, role, profile, and feedback guards
├── models/
│   └── mongo.py            # Collection index definitions
├── routes/                 # HTTP endpoints grouped by domain
├── services/               # OTP, imports, warranty, settings, and helpers
├── scripts/                # Data inspection and maintenance utilities
└── requirements.txt
```

## Getting started

### Prerequisites

- Python 3.11 or newer
- MongoDB locally or a MongoDB Atlas cluster
- Brevo API credentials for real OTP email delivery

### Installation

```bash
git clone https://github.com/karamveersingh22/warranty_portal_backend.git
cd warranty_portal_backend
python -m venv venv
```

Activate the virtual environment:

```bash
# macOS / Linux
source venv/bin/activate

# Windows PowerShell
venv\Scripts\Activate.ps1
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Create and configure the environment file:

```bash
cp .env.example .env
```

Start the API:

```bash
uvicorn main:app --reload
```

The service will be available at:

- API: [http://localhost:8000](http://localhost:8000)
- Interactive Swagger documentation: [http://localhost:8000/docs](http://localhost:8000/docs)
- ReDoc documentation: [http://localhost:8000/redoc](http://localhost:8000/redoc)
- Health check: [http://localhost:8000/health](http://localhost:8000/health)

## Environment variables

| Variable | Required | Description |
| --- | --- | --- |
| `MONGODB_URL` | Yes | MongoDB connection string |
| `DATABASE_NAME` | Yes | Application database name |
| `JWT_SECRET` | Yes | Strong secret used to sign access tokens |
| `JWT_ALGORITHM` | No | JWT algorithm; defaults to `HS256` |
| `JWT_EXPIRY_HOURS` | No | Access-token lifetime; defaults to `24` |
| `BREVO_API_KEY` | Production | Brevo transactional email API key |
| `BREVO_SENDER_EMAIL` | Production | Verified sender email address |
| `BREVO_SENDER_NAME` | No | Sender name shown on OTP emails |
| `OTP_EXPIRY_MINUTES` | No | OTP validity; defaults to `10` |
| `OTP_MAX_RESEND` | No | Maximum resend count; defaults to `3` |
| `ADMIN_EMAIL` | Yes | One admin email or a comma-separated list |
| `FRONTEND_URL` | Yes | One allowed frontend origin or a comma-separated list |
| `ENVIRONMENT` | Yes | Use `production` to send OTP emails through Brevo |
| `DEBUG` | No | Application debug setting |

Never commit `.env` or real credentials. Use a long, random `JWT_SECRET` in production.

## Main API areas

All application routes use the `/api` prefix unless noted otherwise.

| Area | Representative endpoints | Access |
| --- | --- | --- |
| Authentication | `POST /auth/send-otp`, `POST /auth/verify-otp`, `GET /auth/me` | Public / authenticated |
| Customer profile | `/customer/register`, `/customer/profile` | Public / customer |
| Products | `/pieces/lookup/{piece}`, `/pieces/search`, `/pieces/trace/{piece}` | Customer / admin |
| Registrations | `/warranty/register`, `/registrations`, approval and decline actions | Customer / admin |
| Warranties | `/warranty/my-products`, `/warranty/product/{piece}` | Customer |
| Rules | `/rules`, `/rules/categories` | Role-aware / admin |
| Enquiries | `/enquiry`, `/enquiry/my`, `/enquiry/all` | Customer / admin |
| Feedback | `/feedback` | Customer / admin |
| Dealers | `/dealers/nearby` | Customer |
| Support | `/support/contacts` | Customer / admin |
| Imports | `/upload/dbf`, `/upload/jobs/{job_id}`, `/upload/batches` | Admin |
| Catalogue | `/catalogue/status`, `/catalogue/file`, `POST /catalogue` | Public / admin |
| Administration | `/admin/stats`, customer management | Admin |

FastAPI's generated `/docs` page is the authoritative request/response reference.

## Data model

The application manages these primary MongoDB collections:

- `customers`
- `otp_sessions`
- `product_pieces`
- `registration_requests`
- `registered_products`
- `warranty_rules`
- `enquiries`
- `customer_feedbacks`
- `import_batches`
- `support_contacts`
- `app_settings`
- `catalogue_settings`
- `catalogue_files.files` and `catalogue_files.chunks` (GridFS)

Important uniqueness constraints include:

- One imported record per piece number
- One approved registration per piece number
- One OTP session per email and role
- One feedback submission per customer and piece

Indexes are prepared automatically when the application connects to MongoDB.

## DBF import

The importer expects two files:

- `BOOKSALE.dbf` — company dispatch, distributor, and dealer traceability
- `SERIALS.dbf` — individual product pieces and item descriptions

Records are joined through `MAIN_KEY`. Product category, type, and size are decoded from item data, while duplicate piece numbers are handled through idempotent upserts. Imports run as background jobs so the admin frontend can poll progress without holding one long HTTP request open.

## Warranty rules

- Online warranty registration applies only to products whose company dispatch date is on or after **1 April 2025**.
- Warranty rules are associated with decoded product categories.
- Warranty coverage begins on the customer-supplied dealer bill date.
- Future purchase dates are rejected.
- A configurable threshold flags possible old stock using the interval between company dispatch and customer purchase.
- Customers can view rules only for categories represented by their approved products.

## Security model

- Passwordless OTP authentication with hashed, expiring OTP records
- JWT bearer tokens on protected endpoints
- Backend-enforced customer/admin authorization
- Admin role derived only from configured `ADMIN_EMAIL` values
- Normalized lowercase emails
- Profile-completion and feedback-completion guards
- Unique database indexes for ownership and duplicate prevention
- Server-side validation of invoice dates and confirmation values
- Customer-safe product responses that omit distributor and company-dispatch details
- PDF extension, MIME type, size, and file-signature validation
- Explicit CORS origin allow-list

## Production deployment

For a Render Web Service whose repository root is this directory:

- **Build command:** `pip install -r requirements.txt`
- **Start command:** `uvicorn main:app --host 0.0.0.0 --port $PORT`
- **Health-check path:** `/health`

Configure every production environment variable in Render, set `ENVIRONMENT=production`, and set `FRONTEND_URL` to the deployed frontend origin. The catalogue is stored in MongoDB GridFS rather than the server filesystem, so it persists across service restarts.

## Related repository

- [Safrina Warranty Portal — React frontend](https://github.com/karamveersingh22/warranty_portal_frontend)

---

Built for **Safrina Mattress** — *Pamper yourself.*
