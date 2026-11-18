# Offline Changes

A Frappe app that receives the changes a device captured while it was offline, applies them to the records of the site, and holds for a person the ones that conflict with what the site holds now.

It is the server side only. The offline app that captures the changes, stores them on the device and sends them is not part of it.

## What it does

- **Receives** changes in batches, each change being one record and one operation: create, update or delete.
- **Records** every change in a queue before applying it. The queue is the record of what each device sent and what became of it.
- **Compares** an update field by field. The device sends, for each field, the value it started from and the new one, so two people who changed different fields of a record are merged without anyone's help.
- **Decides** a conflict by rules an administrator edits: which value wins, or whether a person chooses.
- **Applies** a change as the user who sent it, with the rights that user has when it arrives. Access lost while offline is access lost.
- **Keeps** every value that lost until a reviewer has seen it.

## Situations and outcomes

| Situation | Outcome on a new site | An administrator may choose instead |
|---|---|---|
| Record unchanged since the device read it | Applied | Not a rule |
| Different fields changed on each side | Merged | Held for review |
| Same field changed to different values | The last to arrive wins, the other value kept | The server's value stays, or held for review |
| Changed on the device, deleted on the server | Held for review | The deletion stands |
| Changed on the device, replaced on the server by another record | Applied to the replacement | Held for review |
| Deleted on the device, changed on the server | Held for review | Not a rule |
| The user may no longer make the change | Refused, kept for a reviewer | Not a rule |
| The record's own validation refuses the change | Failed, kept for a reviewer | Not a rule |
| A change already received | Ignored, its first outcome returned | Not a rule |

A change is applied whole or not at all: one field held for review holds the others with it.

## Requirements

- Frappe 16
- Python 3.14

## Installation

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app $URL_OF_THIS_REPO --branch develop
bench --site $SITE install-app frappe_offline_changes
```

## Configuration

**Offline Change Settings** (System Manager):

- *Receive Changes Captured Offline* switches the app on. It is off after installation.
- *DocTypes That May Be Changed Offline* lists each DocType, and whether a device may create, update or delete its records. A change for any other DocType is refused and kept. Two optional fields per DocType tell the app about its records without any code:
  - *Scope Field*: the link field that names the business unit a record belongs to. The scope narrows a rule and decides which reviewers see a change.
  - *Replaced-By Field*: the link field that names the record that took this one's place, a duplicate merged into another for example. A change to the replaced record follows it.
- *Reviewers See Changes Without a Scope*: left off, a change whose record belongs to no business unit is seen by System Managers only.
- *Changes per Batch* limits one call.
- *Days Applied Values Are Kept*: after this, the values of a change that was applied are removed from the queue. The record's own history keeps them.

**Conflict Rule** (System Manager): one rule per situation is created at installation. A rule may be narrowed to a DocType, to one of its fields, and to a scope. The narrowest rule that fits decides: a rule for the record's scope first, then a rule for the field, then for the DocType.

**Offline Change Reviewer** is the role of the people who resolve, reject and close changes in the **Offline Change** list.

**Offline Review Scope** (System Manager) lists which reviewer handles which scope. A reviewer sees the changes of the scopes listed for them and no other. System Managers see every change.

## For the device

Both calls are made by the signed-in user.

`POST /api/method/frappe_offline_changes.api.changes.submit`

```json
{
  "device_id": "tablet-1",
  "changes": [
    {
      "change_id": "018f3c5e-7a10-7c3e-9b1d-2f4a6c8e0b12",
      "operation": "Update",
      "doctype": "ToDo",
      "name": "a1b2c3d4e5",
      "base_modified": "2026-11-17 09:12:44.120000",
      "captured_on": "2026-11-18 14:03:10",
      "fields": { "priority": { "from": "Medium", "to": "High" } },
      "rows": {
        "table_field": {
          "added": [{ "field": "value" }],
          "changed": { "row-name": { "field": { "from": "old", "to": "new" } } },
          "removed": ["row-name"]
        }
      }
    }
  ]
}
```

- `change_id` is generated on the device. A batch sent twice is applied once.
- `base_modified` is the record's `modified` when the device read it. Leave it empty for a record the device created and has not sent yet.
- `scope`, optional, is the business unit the device believes the record belongs to. The server reads the scope from the record and uses this only when nothing is left of the record.
- A creation sends `values` in place of `fields`. Where the DocType is named by UUID the device's name is kept; elsewhere the server names the record, and later changes sent under the device's name find it.
- The call returns at once with the batch id. The changes are applied in a background job, in the order sent.

`POST /api/method/frappe_offline_changes.api.changes.status` with `{"change_ids": [...]}` returns, for the user's own changes, the status (`Received`, `Applied`, `Held`, `Refused`, `Failed`, `Resolved`, `Rejected`), the reason, the record's name and the outcome per field.

## For the app that owns a DocType

This app knows no DocType but its own. Where the scope and the replacement are fields of the record, the settings above are enough and the owning app changes nothing. Where they are not, or where the app already knows who reviews what, it answers through hooks, described in [`utils/extensions.py`](frappe_offline_changes/utils/extensions.py). A hook is asked before the settings:

| Hook | Question |
|---|---|
| `scope` | Which business unit does this record belong to. Narrows a rule, and decides which reviewers see a change |
| `replaced_by` | Has this record been replaced by another, a duplicate merged for example |
| `apply` | How is a change saved, where the document API is not the right entry point |
| `after_create` | What follows a creation |
| `offline_change_reviewer_scopes` | Which scopes does this reviewer handle, in place of the Offline Review Scope list |

A DocType with neither hook nor setting has no scope, is never replaced, and is saved through the document API with Frappe's permissions.

## Development

```bash
cd apps/frappe_offline_changes
pre-commit install
bench --site $SITE run-tests --app frappe_offline_changes
```

Four kinds of test, from the code outwards:

| What | Where | Needs |
|---|---|---|
| Every situation, rule and reviewer action, called directly and rolled back | `tests/test_changes.py` | Frappe alone: the records are its own ToDo, Contact and Language |
| The same app on Unified Case Management persons: delegations, a right withdrawn, a person merged | `tests/test_ucm.py` | The `ucm` app; skipped without it |
| Devices over HTTP, through the web server and the background worker | `tests/test_http.py` | The site served and a worker running; skipped otherwise |
| A reviewer at the review screen, in a browser | `e2e/run.sh <site>` | A development site being served, and a Python with Playwright (`E2E_PYTHON`) |

The last two commit what they create, since other processes must see it, and remove it afterwards. `tests/device.py` is the device they use: it speaks HTTP only, and is the shortest example of what an offline app sends. See [CONTRIBUTING.md](CONTRIBUTING.md).

## Translations

Every user-facing string is translatable. Generate the template with `bench generate-pot-file --app frappe_offline_changes`; translations live in `frappe_offline_changes/locale/<lang>.po`.

## Security

A queue row holds values of the record it concerns. It is visible to System Managers and to the reviewers of the record's scope, never to the user who sent it, who asks for the outcome through the `status` call. The scope is read on the server, from the record or from what Frappe kept of a deleted one, so a device cannot route a change to other reviewers. Report a vulnerability privately: see [SECURITY.md](SECURITY.md).
