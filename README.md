## E Signature for Frappe and ERPNext

Get documents signed without leaving your site. Send any record or PDF for
signing, let people draw or upload their signature, and get back a signed PDF
with a full record of who signed and when.

> [!WARNING]
> **This is not a cryptographic (PKI) signature.** The app places a signature
> image on the PDF and keeps an audit trail (name, email, time and IP address).
> It does not add a digital certificate to the file.
>
> If you are interested in [Documenso](https://github.com/documenso/documenso),
> which supports cryptographic signing, use the
> [Documenso integration for ERPNext](https://github.com/jasjastone/sign).

### Features

- **Sign any document type.** Turn on signing for a doctype with one settings
  record. No code needed.
- **Sign uploaded PDFs.** Upload a PDF (or merge several into one) and send it
  for signing, even with no record behind it.
- **Many kinds of signers.** System users, Employees, Customers, Suppliers or
  any email address.
- **Signers stay on your site.** Users sign from the record. Everyone else
  signs from a secure link sent by email.
- **Place boxes on the PDF.** Click the page to add signature, name and date
  boxes for each signer. Name and date are filled in for them.
- **Draw or upload a signature.** The last signature is remembered, so the next
  document takes one click.
- **Signing order.** Let everyone sign at once, or one after another.
- **Email reminders.** Sent automatically to people who have not signed yet,
  and you can send one any time.
- **Reject with a reason.** One rejection stops the whole request.
- **Withdraw a request.** Take it back to edit the record, then send again.
- **Locked while out for signing.** The record cannot be changed while people
  are signing it.
- **Submit rules.** Block submitting until everyone has signed, or submit
  automatically once they have.
- **Audit trail.** Name, email, time and IP address saved for every signer.
- **Sign dashboard.** See what is waiting for you and what you have sent.
- **Access control.** Only users with the **Sign User** role can send requests,
  and they only see their own.

### Supported versions

Frappe v14, v15 and v16.

### Install

```bash
bench get-app frappe_sign
bench --site <site> install-app frappe_sign
```

Give the **Sign User** role to everyone who should send documents for signing.

> [!NOTE]
> To show letter head headers and footers in the PDF, the server needs the
> "patched qt" version of wkhtmltopdf. Check with `wkhtmltopdf -V`. If it does
> not say "with patched qt", install it from
> [wkhtmltopdf releases](https://github.com/wkhtmltopdf/packaging/releases).

### How to use

**Sign a record**

1. Create a **Signable Document Type**. Choose the doctype and print format.
2. Open a record of that doctype and click **Request Signature**.
3. Add signers and click the PDF to place their boxes.
4. Send. Each signer gets an email with their signing link.

**Sign an uploaded PDF**

1. Create a new **Signature Request** and attach the PDF.
2. Save, then click **Request Signature**.

**Track your requests**

Open **Sign** (`/app/sign-dashboard`).

### Settings

Go to **Signature Settings** to:

- Set how many days a signing link stays valid.
- Turn reminders off.
- Set the largest size for signature images.

### For developers

**Default signers.** Add `get_signers()` to a doctype's controller and
**Request Signature** opens with those signers already listed, in that order.

```python
class EngagementAgreement(Document):
    def get_signers(self):
        return [
            {"signer_type": "Employee", "signer_reference": self.employee},
            {"signer_type": "User", "signer_reference": self.ceo_signer},
            {"signer_type": "Email", "signer_name": "Jane Doe", "signer_email": "jane@example.com"},
        ]
```

- `signer_type`: `User`, `Employee`, `Customer`, `Supplier` or `Email`.
  Anything other than `User` needs **Allow External Signers** turned on.
- `signer_reference`: the record name. The name and email come from it.
- `signer_email` and `signer_name`: only for `Email` signers.

**Run the tests**

```bash
bench --site <site> execute frappe_sign.frappe_sign.test_sign_flow.run
```

It creates its own data, checks the full signing flow, then removes the data.

### License

MIT
