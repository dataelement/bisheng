"""F043: object names for files uploaded inside a conversation.

Daily-mode uploads used to be stored under the raw filename, so two users who
both uploaded "1.png" overwrote each other -- harmless while the bucket was
wiped every 3 days, a permanent data leak once the files stopped expiring.
Names are now uuid-based and prefixed by conversation.

See features/v2.6.0/043-chat-file-permanent-storage/design.md §3 decision 1.
"""

from bisheng.core.storage.chat_attachment import CHAT_OBJECT_PREFIX, build_chat_object_name


class TestBuildChatObjectName:
    def test_same_filename_never_collides(self):
        # AC-02 — the whole point: one user's upload must not clobber another's.
        a = build_chat_object_name(1, "1.png")
        b = build_chat_object_name(1, "1.png")
        assert a != b

    def test_scoped_to_the_uploader(self):
        # Grouping by uploader keeps ops/quota work tractable later; deletion
        # itself reads object names off the messages (see module docstring).
        name = build_chat_object_name(42, "report.pdf")
        assert name.startswith(f"{CHAT_OBJECT_PREFIX}42/")

    def test_extension_preserved_and_lowercased(self):
        assert build_chat_object_name(7, "Photo.PNG").endswith(".png")

    def test_filename_without_extension(self):
        name = build_chat_object_name(7, "README")
        assert "." not in name.rsplit("/", 1)[-1]

    def test_path_separators_in_filename_cannot_escape_the_prefix(self):
        # The name is built from user-supplied content; a filename must never be
        # able to steer the object somewhere else in the bucket.
        name = build_chat_object_name(7, "../../etc/passwd")
        assert name.startswith(f"{CHAT_OBJECT_PREFIX}7/")
        assert ".." not in name

    def test_windows_separators_are_not_taken_as_extension(self):
        name = build_chat_object_name(7, r"C:\tmp\evil.exe")
        assert name.startswith(f"{CHAT_OBJECT_PREFIX}7/")
        assert "\\" not in name
        assert name.endswith(".exe")

    def test_absurdly_long_extension_is_dropped(self):
        # A "." in a long name doesn't make everything after it an extension.
        name = build_chat_object_name(7, "file." + "x" * 50)
        assert name.startswith(f"{CHAT_OBJECT_PREFIX}7/")
        assert len(name.rsplit("/", 1)[-1]) < 60

    def test_hidden_file_has_no_extension(self):
        name = build_chat_object_name(7, ".gitignore")
        assert "." not in name.rsplit("/", 1)[-1]
