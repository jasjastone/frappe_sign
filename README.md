## Sign

Embedded e-signature for ERPNext. Signers never leave your domain: system users
sign in a dialog on the record, everyone else signs on `/sign-document?key=<token>`.

This is **not** a cryptographic or PKI signature. It is a drawn or uploaded
signature image stamped into the PDF, plus an audit trail (name, email,
timestamp, IP, and any rejection reason).

### Setup

```bash
bench get-app frappe_sign
bench --site <site> install-app frappe_sign
```

`PyMuPDF` is installed with the app. PDF snapshots are rendered exactly like
the print view's PDF button, so they carry the document's letter head.

Letter head headers and footers need the **patched-Qt** build of wkhtmltopdf
(`wkhtmltopdf -V` must say "with patched qt"). Distro packages are usually
unpatched and silently drop them — install the build from
https://github.com/wkhtmltopdf/packaging/releases instead.

### Enabling a doctype

Add one **Signable Document Type** row — document type, print format, and
whether non-User signers are allowed. No code, ever. A "Request Signature"
button then appears on that doctype's form.

### Signing a PDF with no record behind it

For letters, contracts or anything made in an office suite: create a new
**Signature Request**, attach the PDF, save, then click **Request Signature**.
The Reference section is filled in by the system only, for requests made from a
record.

### Signing

Requesters add signers (User / Employee / Customer / Supplier / plain Email) and
click the rendered PDF to place one or more signature boxes for each one (one signature fills them all). Every signer gets a
tokenised link; all of them can sign in any order. One rejection rejects the
whole request immediately.

Tick **Signers sign in order** in the request dialog (↑/↓ set the order) to
have them sign one after another instead: each is emailed only when the one
before them has signed, and their link's validity starts then.

Signers who haven't signed are reminded by email every few days (**Signature
Settings → Remind Every (Days)**, default 3, 0 for off) until their link
expires. **Send Reminder** on the record or the request reminds them now.

Signers draw or upload a signature. The last one used is remembered per email
(**Saved Signature**), so the next document is one click; signing with a new
one replaces it.

Open **Sign** (`/app/sign-dashboard`) for what is waiting on you and what you
have sent.

### Checking it still works

```bash
bench --site <site> execute frappe_sign.frappe_sign.test_sign_flow.run
```

Creates its own data, asserts the whole flow, then removes it.

#### License

mit
