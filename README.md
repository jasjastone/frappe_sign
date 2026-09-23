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

### Default signers from code: `get_signers()`

A signable doctype can name its own signers by defining `get_signers()` on its
controller. **Request Signature** then opens with them already listed, in that
order and set to sign in order; the requester only places the boxes.

It returns a list of dicts, one per signer, in signing order:

```python
class EngagementAgreement(Document):
    def get_signers(self):
        return [
            {"signer_type": "Employee", "signer_reference": self.employee},
            {"signer_type": "User", "signer_reference": self.ceo_signer},
            {"signer_type": "Email", "signer_name": "Jane Doe", "signer_email": "jane@example.com"},
        ]
```

| Key | Required | Notes |
|---|---|---|
| `signer_type` | yes | `User`, `Employee`, `Customer`, `Supplier` or `Email`. Anything but `User` needs **Allow External Signers** on the Signable Document Type. |
| `signer_reference` | yes, except `Email` | The record's name. Name and email are always taken from it: User email; Employee preferred → company → personal → user email; Customer / Supplier email, else a linked Contact's, else a linked Address's. |
| `signer_email` | `Email` only | Where the signing link goes. |
| `signer_name` | no (`Email` only) | Defaults to the email. |

Every entry becomes a signer. An entry that can't be used (no email on the
record, unknown type, the same email twice) is shown to the requester as a
warning and the rest still load; a `get_signers()` that raises is logged to
the Error Log and the dialog opens empty. The same reference is shown on the
Signable Document Type form, under **Default Signers (for developers)**.

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

Signers who haven't signed are reminded by email 2 hours, 8 hours, 1 day,
2 days and 4 days after the document reaches them (sent, or their turn came),
then no more. **Signature Settings → Disable Reminders** turns this off.
**Send Reminder** on the record or the request sends an extra one now.

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
