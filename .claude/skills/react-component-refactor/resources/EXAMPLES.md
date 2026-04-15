# React Component Refactoring — Real Examples

These examples are drawn from the `Subscription` module refactoring and demonstrate each pattern in context.

---

## Example 1: Extract Sub-Component

### Before (in `CreateChannelDrawer.tsx`, ~120 lines inline)
```tsx
// Inline sub-component buried inside the main component
function CreateChannelDrawer({ open, onOpenChange, ... }) {
    // ... 18 useState calls ...

    // Inline sub-component — hard to find, test, or reuse
    function SubChannelBlock({ data, onNameChange, ... }) {
        // 120 lines of JSX + local state
    }

    return ( /* uses SubChannelBlock inline */ );
}
```

### After
```
CreateChannel/
├── CreateChannelDrawer.tsx   # imports SubChannelBlock
└── SubChannelBlock.tsx       # standalone, with exported Props interface
```

```tsx
// SubChannelBlock.tsx
export interface SubChannelData { id: string; name: string; ... }

interface SubChannelBlockProps {
    data: SubChannelData;
    onNameChange: (name: string) => void;
    onRemove: () => void;
    // ...
}

export function SubChannelBlock({ data, onNameChange, ... }: SubChannelBlockProps) {
    // self-contained component
}
```

---

## Example 2: Extract Form State Hook

### Before (`CreateChannelDrawer.tsx` — 18 useState + handlers)
```tsx
function CreateChannelDrawer(...) {
    const [channelName, setChannelName] = useState("");
    const [channelDesc, setChannelDesc] = useState("");
    const [visibility, setVisibility] = useState("private");
    const [sources, setSources] = useState([]);
    // ... 14 more useState calls ...

    const resetForm = () => { /* reset all 18 states */ };
    const handleAddSubChannel = () => { /* manipulate subChannels state */ };
    // ... more handlers ...

    return ( /* 400+ lines of JSX using all these states */ );
}
```

### After
```
hooks/
└── useCreateChannelForm.ts    # all 18 states + handlers
CreateChannel/
└── CreateChannelDrawer.tsx    # clean UI component
```

```tsx
// hooks/useCreateChannelForm.ts
export function useCreateChannelForm() {
    const [channelName, setChannelName] = useState("");
    // ... all states ...
    const resetForm = () => { /* ... */ };
    const handleAddSubChannel = () => { /* ... */ };

    return { channelName, setChannelName, ..., resetForm, handleAddSubChannel };
}

// CreateChannelDrawer.tsx — now a presentational component
function CreateChannelDrawer(...) {
    const form = useCreateChannelForm();
    return (
        <Input value={form.channelName} onChange={e => form.setChannelName(e.target.value)} />
        // ... form.visibility, form.handleAddSubChannel, etc.
    );
}
```

---

## Example 3: Extract Data Manager Hook

### Before (`AddSourceDropdown.tsx` — 497 lines with data loading + UI)
```tsx
function AddSourceDropdown({ sources, onSourcesChange, expanded, ... }) {
    const [wechatSources, setWechatSources] = useState([]);
    const [websiteSources, setWebsiteSources] = useState([]);
    const [searchKeyword, setSearchKeyword] = useState("");

    // Data loading effect
    useEffect(() => {
        if (!expanded) return;
        const load = async () => { /* API call + state mapping */ };
        load(currentType);
    }, [expanded, activeTab]);

    // WeChat auto-detection effect
    useEffect(() => { /* 50 lines of async logic */ }, [expanded, viewMode]);

    // Filtering logic
    const filteredSources = useMemo(() => { /* ... */ }, [...]);

    return ( /* 200+ lines of UI */ );
}
```

### After
```
hooks/
└── useSourceManager.ts        # API calls, filtering, toggle logic
CreateChannel/
└── AddSourceDropdown.tsx      # pure UI (328 lines, down from 497)
```

```tsx
// AddSourceDropdown.tsx — clean separation
function AddSourceDropdown({ sources, onSourcesChange, expanded, ... }) {
    const mgr = useSourceManager(sources, onSourcesChange, expanded, onExpandChange);

    return (
        <Input value={mgr.searchKeyword} onChange={e => mgr.setSearchKeyword(e.target.value)} />
        // ... mgr.filteredSources, mgr.toggleSource, mgr.handleConfirm, etc.
    );
}
```

---

## Example 4: Extract Validation to Utility

### Before (inline in submit handler — 45 lines of validation)
```tsx
onClick={async () => {
    if (form.sources.length < 1) { showToast({ message: "..." }); return; }
    if (!form.channelName.trim()) { showToast({ message: "..." }); return; }
    if (form.contentFilter) {
        const err = validateFilterGroups(form.filterGroups);
        if (err) { showToast({ message: err }); return; }
    }
    if (form.createSubChannel) {
        for (const sub of form.subChannels) { /* more checks */ }
    }
    // ... then build data and submit
}}
```

### After
```tsx
// channelUtils.ts — pure validation function
export function validateCreateChannelForm(
    data: CreateChannelFormData,
    localize: (key: string) => string
): string | null {
    if (data.sources.length < 1) return localize("need_one_source") || "至少需添加 1 个信息源";
    if (!data.channelName.trim()) return localize("cannot_empty_channel_name");
    // ... all checks ...
    return null;
}

// CreateChannelDrawer.tsx — clean submit handler
onClick={async () => {
    const data = { /* assemble form data */ };
    const error = validateCreateChannelForm(data, localize);
    if (error) { showToast({ message: error, severity: "warning" }); return; }
    // submit
}}
```
