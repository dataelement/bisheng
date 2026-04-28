"""Constants shared by F006 permission migration scripts."""

ACCESS_TYPE_MAPPING: dict[int, tuple[str, str]] = {
    # AccessType.value -> (object_type, relation)
    1: ('knowledge_library', 'viewer'),  # KNOWLEDGE
    3: ('knowledge_library', 'editor'),  # KNOWLEDGE_WRITE
    5: ('assistant', 'viewer'),  # ASSISTANT_READ
    6: ('assistant', 'editor'),  # ASSISTANT_WRITE
    7: ('tool', 'viewer'),  # GPTS_TOOL_READ
    8: ('tool', 'editor'),  # GPTS_TOOL_WRITE
    9: ('workflow', 'viewer'),  # WORKFLOW
    10: ('workflow', 'editor'),  # WORKFLOW_WRITE
    11: ('dashboard', 'viewer'),  # DASHBOARD
    12: ('dashboard', 'editor'),  # DASHBOARD_WRITE
    # 99: WEB_MENU -> not migrated
}

KNOWLEDGE_LEGACY_TYPES = {'knowledge_library': 'knowledge_space'}

GROUP_RESOURCE_TYPE_MAPPING: dict[int, tuple[str, ...]] = {
    1: ('knowledge_library', 'knowledge_space'),  # KNOWLEDGE
    3: ('assistant',),  # ASSISTANT
    4: ('tool',),  # GPTS_TOOL
    5: ('workflow',),  # WORK_FLOW
    6: ('dashboard',),  # DASHBOARD
}

FLOW_TYPE_MAPPING: dict[int, str] = {
    5: 'assistant',  # ASSISTANT
    10: 'workflow',  # WORKFLOW
    # 15, 20, 25, 30 -> not migrated
}

RELATION_PRIORITY: dict[str, int] = {
    'owner': 4,
    'manager': 3,
    'editor': 2,
    'viewer': 1,
}

SCM_ROLE_MAPPING: dict[str, str] = {
    'creator': 'owner',
    'admin': 'manager',
    'member': 'viewer',
}

SCM_TYPE_MAPPING: dict[str, str] = {
    'space': 'knowledge_space',
    'channel': 'channel',
}

_BATCH_SIZE = 100
_CHECKPOINT_FILENAME = 'migration_f006_checkpoint.json'
