from bisheng.common.errcode.flow import WorkflowRegistrationConflict, WorkflowRegistrationDenied


class RegistrationSync:
    def __init__(self, repository, scope, codec, can_read):
        self.repository = repository
        self.scope = scope
        self.codec = codec
        self.can_read = can_read

    def snapshot(self, page_token=None, limit=100):
        expires_at = None
        if page_token:
            page = self.codec.read(self.scope, "snapshot", page_token)
            base, after = page["base"], page["after"]
            expires_at = page["expires_at"]
        else:
            base, after = self.repository.highwater(self.scope), ""
        rows, more = self.repository.catalog_page(self.scope, base, after, limit)
        return {
            "items": [row for row in rows if self.can_read(row["workflow_id"])],
            "base": base,
            "base_cursor": self.codec.issue(self.scope, "checkpoint", position=base),
            "page_token": self.codec.issue(
                self.scope, "snapshot", expires_at=expires_at, base=base, after=rows[-1]["workflow_id"]
            )
            if more
            else None,
        }

    def changes(self, *, cursor=None, page_token=None, limit=100):
        if bool(cursor) == bool(page_token):
            raise WorkflowRegistrationConflict()
        expires_at = None
        if page_token:
            window = self.codec.read(self.scope, "window", page_token)
            after, high = window["position"], window["high"]
            expires_at = window["expires_at"]
        else:
            after = self.codec.read(self.scope, "checkpoint", cursor)["position"]
            high = None
        rows, high, more = self.repository.change_page(self.scope, after, high, limit)
        position = rows[-1]["sequence"] if more else high
        return {
            "items": [row for row in rows if self.can_read(row["workflow_id"])],
            "high": high,
            "next_cursor": self.codec.issue(self.scope, "checkpoint", position=position),
            "page_token": self.codec.issue(self.scope, "window", expires_at=expires_at, position=position, high=high)
            if more
            else None,
        }

    def version(self, workflow_id, version_id):
        if not self.can_read(workflow_id):
            raise WorkflowRegistrationDenied()
        return self.repository.version(self.scope, workflow_id, version_id)

    def receipt(self, receipt):
        if not self.can_read(receipt.workflow_id):
            raise WorkflowRegistrationDenied()
        if not receipt.workflow_version_id.isascii() or not receipt.workflow_version_id.isdecimal():
            raise WorkflowRegistrationConflict()
        return self.repository.apply_receipt(self.scope, receipt)
