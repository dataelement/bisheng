window.__ModuleLoader__.load({
	id: "dsh-ppt",
	factory: (require) => {
		var module = { exports: {} };
		var exports = module.exports;
		Object.defineProperty(exports, Symbol.toStringTag, { value: "Module" });
		let react = require("react");
		let _deepseek_ai_dsh_client_ui_primitives = require("@deepseek-ai/dsh-client-ui-primitives");
		let react_jsx_runtime = require("react/jsx-runtime");
		//#region src/protocol.ts
		/**
		* Resolve workflow availability while preserving compatibility with older extracted templates.
		* @param template - Persisted or built-in template definition.
		* @param mode - Presentation workflow requesting the template.
		* @returns Whether the template is available to the requested workflow.
		*/
		function templateSupportsMode(template, mode) {
			return template.supportedModes?.includes(mode) ?? true;
		}
		//#endregion
		//#region src/client/curated-previews.ts
		/** Browser preview registry for every source-backed catalog template. */
		/** Content-addressed local image URLs; both clients share the core JPG files. */
		const CURATED_TEMPLATE_PREVIEWS = /* GENERATED_PPT_PREVIEWS */ {};
		//#endregion
		//#region \0dsh-css:ppt-composer.css.mjs
		const css = "._3723UG_modeRoot{box-sizing:border-box;width:100%;padding:0 var(--dsh-composer-side-clearance);position:relative}._3723UG_modeRow{flex-wrap:wrap;justify-content:flex-start;align-items:center;gap:8px;min-height:32px;display:flex}._3723UG_modeChip{border:1px solid var(--dsw-alias-border-l2-darkmode-thin);color:var(--dsw-alias-label-secondary);font:inherit;cursor:pointer;background:0 0;border-radius:999px;align-items:center;gap:6px;padding:7px 13px;font-size:12px;line-height:16px;display:inline-flex}._3723UG_modeChip:hover{background:var(--dsw-alias-interactive-bg-hover);color:var(--dsw-alias-label-primary)}._3723UG_modeChip[data-selected=true]{border-color:color-mix(in srgb, var(--dsw-alias-state-business-primary) 55%, transparent);background:color-mix(in srgb, var(--dsw-alias-state-business-primary) 12%, transparent);color:var(--dsw-alias-state-business-primary)}._3723UG_templatePanel{box-sizing:border-box;z-index:2;width:100%;max-width:calc(var(--dsh-composer-card-max-width) + 32px);height:var(--office-ppt-template-panel-height,calc(100dvh - 178px));max-height:var(--office-ppt-template-panel-height,calc(100dvh - 178px));background:0 0;flex-direction:column;margin-top:8px;display:flex;position:absolute;top:100%;left:50%;overflow:hidden;transform:translate(-50%)}._3723UG_modeRoot[data-placement=fixed]{height:0;overflow:visible}._3723UG_modeRoot[data-placement=fixed] ._3723UG_templatePanel{max-height:none;top:0}._3723UG_modeRoot[data-placement=fixed] ._3723UG_templateViewport{overscroll-behavior:contain;flex:auto;padding-bottom:12px;overflow-y:auto}._3723UG_templateToolbar{padding-inline:4px;z-index:2;background:0 0;flex:none;justify-content:space-between;align-items:center;gap:12px;min-height:38px;display:flex;position:relative}._3723UG_templateViewport{box-sizing:border-box;overscroll-behavior:contain;scrollbar-width:none;min-height:0;padding:4px 4px 12px;overflow-x:hidden;overflow-y:auto}._3723UG_templateViewport::-webkit-scrollbar{display:none}._3723UG_categoryTabs{scrollbar-width:none;gap:4px;min-width:0;display:flex;overflow-x:auto}._3723UG_categoryTabs::-webkit-scrollbar{display:none}._3723UG_categoryTabs button{color:var(--dsw-alias-label-caption);font:inherit;cursor:pointer;background:0 0;border:0;border-radius:999px;flex:none;padding:5px 10px;font-size:11px;line-height:16px}._3723UG_categoryTabs button:hover{color:var(--dsw-alias-label-primary)}._3723UG_categoryTabs button[data-selected=true]{background:var(--dsw-alias-interactive-bg-hover);color:var(--dsw-alias-label-primary)}._3723UG_templateGrid{background:0 0;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px 14px;display:grid}._3723UG_templateCard{min-width:0;min-height:0;position:relative}._3723UG_templateSelect{width:100%;min-width:0;color:var(--dsw-alias-label-tertiary);font:inherit;cursor:pointer;background:0 0;border:0;outline:0;flex-direction:column;padding:0;display:flex}._3723UG_previewViewport,._3723UG_selectionPreview{container-type:inline-size}._3723UG_previewViewport{box-sizing:border-box;aspect-ratio:16/9;border:2px solid #0000;border-radius:9px;width:100%;transition:border-color .12s,transform .12s;display:block;position:relative;overflow:hidden}._3723UG_previewViewport>._3723UG_preview{aspect-ratio:auto;width:100%;height:100%;animation:.18s _3723UG_previewReveal}@keyframes _3723UG_previewReveal{0%{opacity:.72}to{opacity:1}}._3723UG_templateCard:hover ._3723UG_previewViewport{transform:translateY(-1px)}._3723UG_templateSelect:active ._3723UG_previewViewport{transform:scale(.985)}._3723UG_templateCard[data-selected=true] ._3723UG_previewViewport{border-color:var(--dsw-alias-state-business-primary)}._3723UG_templateSelect:focus-visible ._3723UG_previewViewport{outline:2px solid var(--dsw-alias-state-business-primary);outline-offset:2px}._3723UG_templateName{text-align:center;text-overflow:ellipsis;white-space:nowrap;padding-top:5px;font-size:12px;line-height:16px;overflow:hidden}._3723UG_templateCard[data-selected=true] ._3723UG_templateName{color:var(--dsw-alias-label-primary)}._3723UG_panelState{min-height:160px;color:var(--dsw-alias-label-tertiary);place-items:center;gap:10px;font-size:12px;display:grid}._3723UG_templateError{border:1px solid color-mix(in srgb, var(--dsw-alias-state-error-primary) 40%, transparent);background:color-mix(in srgb, var(--dsw-alias-state-error-primary) 10%, transparent);color:var(--dsw-alias-state-error-primary);border-radius:8px;margin-bottom:8px;padding:7px 10px;font-size:11px;line-height:16px}._3723UG_retryButton{border:1px solid var(--dsw-alias-border-l2-darkmode-thin);color:var(--dsw-alias-label-secondary);font:inherit;cursor:pointer;background:0 0;border-radius:999px;padding:6px 12px}._3723UG_retryButton:hover{background:var(--dsw-alias-interactive-bg-hover);color:var(--dsw-alias-label-primary)}._3723UG_selection{align-items:flex-start;display:flex}._3723UG_selectionPreview{aspect-ratio:16/9;transform-origin:50%;flex:none;width:clamp(76px,10vw,92px);transition:transform .2s cubic-bezier(.34,1.56,.64,1);display:block;position:relative;transform:rotate(-3deg)scale(1)}._3723UG_selectionFrame{border:2px solid var(--dsw-alias-state-business-primary);background:var(--dsw-alias-bg-base);border-radius:9px;width:100%;height:100%;display:block;overflow:hidden;box-shadow:0 4px 14px #0000002e}._3723UG_selectionRemove{z-index:2;color:#fff;opacity:0;pointer-events:none;cursor:pointer;background:#111111e0;border:1px solid #ffffff4d;border-radius:50%;place-items:center;width:20px;height:20px;padding:0;font:500 15px/1 ui-sans-serif,system-ui,sans-serif;transition:opacity .12s,transform .12s;display:grid;position:absolute;top:-8px;right:-8px;transform:rotate(3deg)scale(.88);box-shadow:0 3px 10px #00000047}._3723UG_selectionPreview:hover ._3723UG_selectionRemove,._3723UG_selectionPreview:focus-within ._3723UG_selectionRemove{opacity:1;pointer-events:auto;transform:rotate(3deg)scale(1)}._3723UG_selectionRemove:focus-visible{outline:2px solid var(--dsw-alias-state-business-primary);outline-offset:2px}._3723UG_preview{box-sizing:border-box;aspect-ratio:16/9;background:var(--office-bg);color:var(--office-text);flex-direction:column;justify-content:center;padding:12% 10%;display:flex;position:relative;overflow:hidden}._3723UG_preview[data-source-preview=true]{background:#fff;padding:0}._3723UG_preview[data-source-preview=true]:before,._3723UG_preview[data-source-preview=true]:after{display:none}._3723UG_previewImage{object-fit:cover;-webkit-user-drag:none;width:100%;height:100%;display:block;position:absolute;inset:0}._3723UG_preview:before,._3723UG_preview:after{content:\"\";pointer-events:none;position:absolute}._3723UG_preview:before{border-left:1px solid color-mix(in srgb, var(--office-accent) 35%, transparent);background:color-mix(in srgb, var(--office-surface) 92%, transparent);width:34%;height:100%;top:0;right:0}._3723UG_preview:after{background:var(--office-accent);width:18%;height:clamp(1px,1.3cqi,3px);bottom:13%;right:8%}._3723UG_previewAccent{background:var(--office-accent);width:18%;height:clamp(1px,1.3cqi,3px);position:absolute;top:16%;left:10%}._3723UG_preview strong,._3723UG_preview small{z-index:1;text-overflow:ellipsis;white-space:nowrap;width:66%;display:block;position:relative;overflow:hidden}._3723UG_preview strong{margin-top:8%;font-size:clamp(4px,6cqi,14px);font-weight:650;line-height:1.12}._3723UG_preview small{color:var(--office-muted);margin-top:4px;font-size:clamp(3px,3.4cqi,8px)}._3723UG_preview[data-variant=blue-professional]:before{clip-path:polygon(25% 0,100% 0,100% 100%,0 100%);background:var(--office-surface);border:0;width:40%}._3723UG_preview[data-variant=blue-professional]:after{width:15%;height:2px;bottom:14%;right:8%}._3723UG_preview[data-variant=editorial-forest]{background:var(--office-surface);color:var(--office-accent);justify-content:flex-end;padding:10%;font-family:Georgia,Times New Roman,serif}._3723UG_preview[data-variant=editorial-forest]:before{aspect-ratio:1;border:1px solid var(--office-accent);background:0 0;border-radius:50%;width:16%;height:auto;top:11%;right:9%}._3723UG_preview[data-variant=editorial-forest]:after{background:var(--office-accent);width:80%;height:1px;bottom:10%;right:10%}._3723UG_preview[data-variant=editorial-forest] ._3723UG_previewAccent{background:var(--office-accent);width:26%;height:1px;top:13%}._3723UG_preview[data-variant=editorial-forest] strong,._3723UG_preview[data-variant=editorial-forest] small{width:78%}._3723UG_preview[data-variant=editorial-forest] strong{margin-bottom:11%;font-size:clamp(5px,7.4cqi,17px);font-weight:500}._3723UG_preview[data-variant=editorial-forest] small{color:var(--office-bg);font-family:ui-monospace,SFMono-Regular,Menlo,monospace;position:absolute;top:16%;left:10%}._3723UG_preview[data-variant=signal]{background:var(--office-bg);color:var(--office-text);font-family:Georgia,Times New Roman,serif}._3723UG_preview[data-variant=signal]:before{background-image:linear-gradient(color-mix(in srgb, var(--office-secondary) 55%, transparent) 1px, transparent 1px), linear-gradient(90deg, color-mix(in srgb, var(--office-secondary) 55%, transparent) 1px, transparent 1px);opacity:.45;background-size:18% 31%;border:0;width:100%;height:100%;inset:0}._3723UG_preview[data-variant=signal]:after{background:var(--office-secondary);width:80%;height:1px;bottom:15%;left:10%;right:auto}._3723UG_preview[data-variant=signal] ._3723UG_previewAccent{background:var(--office-accent);width:14%;height:1px;top:18%}._3723UG_preview[data-variant=signal] strong{font-size:clamp(5px,6.8cqi,16px);font-weight:600}._3723UG_preview[data-variant=signal] small{color:var(--office-muted);letter-spacing:.08em;font-family:ui-monospace,SFMono-Regular,Menlo,monospace}._3723UG_preview[data-variant=orange-data]{color:#111;background:#fff;justify-content:flex-start;padding:15% 8%;font-family:Arial,sans-serif}._3723UG_preview[data-variant=orange-data]:before{background:linear-gradient(90deg, var(--office-accent) 0 25%, var(--office-secondary) 25% 50%, #f19309 50% 75%, #f9c22b 75%) 0 21% / 100% 28% no-repeat, linear-gradient(#f2f2f2 0 0) 0 70% / 72% 24% no-repeat;border:0;border-top:clamp(1px,.9cqi,2px) solid #111;width:84%;height:45%;inset:8% 8% auto}._3723UG_preview[data-variant=orange-data]:after{background:#111;width:84%;height:11%;bottom:11%;right:8%}._3723UG_preview[data-variant=orange-data] ._3723UG_previewAccent{background:var(--office-accent);width:22%;height:clamp(1px,.9cqi,2px);top:8%;left:8%}._3723UG_preview[data-variant=orange-data] strong,._3723UG_preview[data-variant=orange-data] small{z-index:2;width:52%}._3723UG_preview[data-variant=orange-data] strong{margin-top:10%;font-size:clamp(4px,5.8cqi,13px)}._3723UG_preview[data-variant=orange-data] small{color:#5b626d;letter-spacing:.06em;font-family:ui-monospace,SFMono-Regular,Menlo,monospace}._3723UG_preview[data-variant=custom]:before{background:linear-gradient(145deg, var(--office-surface), var(--office-secondary));width:40%}._3723UG_preview[data-page=\"1\"],._3723UG_preview[data-page=\"2\"]{background:color-mix(in srgb, var(--office-bg) 92%, var(--office-surface));color:var(--office-text);font-family:var(--font-sans,ui-sans-serif, system-ui, sans-serif);justify-content:flex-start;padding:8% 8% 7%}._3723UG_preview[data-page=\"1\"]:before,._3723UG_preview[data-page=\"2\"]:before{background:linear-gradient(90deg, color-mix(in srgb, var(--office-accent) 13%, transparent) 1px, transparent 1px), linear-gradient(color-mix(in srgb, var(--office-accent) 13%, transparent) 1px, transparent 1px);clip-path:none;opacity:.48;background-size:20% 25%;border:0;width:100%;height:100%;inset:0}._3723UG_preview[data-page=\"1\"]:after,._3723UG_preview[data-page=\"2\"]:after{background:var(--office-accent);width:18%;height:2px;top:8%;bottom:auto;right:8%}._3723UG_preview[data-page=\"1\"] ._3723UG_previewAccent,._3723UG_preview[data-page=\"2\"] ._3723UG_previewAccent{background:color-mix(in srgb, var(--office-muted) 38%, transparent);width:84%;height:1px;top:auto;bottom:7%;left:8%}._3723UG_preview[data-page=\"1\"] strong,._3723UG_preview[data-page=\"2\"] strong{width:78%;margin-top:3%;font-size:clamp(4px,5.3cqi,12px);line-height:1.12}._3723UG_previewEyebrow{letter-spacing:.06em;width:74%!important;color:var(--office-muted)!important;margin:0!important;font:500 clamp(3px,2.7cqi,6px)/1.1 ui-monospace,SFMono-Regular,Menlo,monospace!important}._3723UG_previewKpis{z-index:1;grid-template-columns:repeat(3,minmax(0,1fr));gap:4px;width:100%;margin-top:auto;display:grid;position:relative}._3723UG_previewKpis>span{border:1px solid color-mix(in srgb, var(--office-accent) 18%, transparent);background:color-mix(in srgb, var(--office-surface) 88%, transparent);border-radius:3px;justify-content:space-between;align-items:baseline;min-width:0;padding:7% 8%;display:flex}._3723UG_previewKpis b{font-size:clamp(4px,4.8cqi,11px);font-weight:700}._3723UG_previewKpis i{color:var(--office-muted);font:clamp(2px,2.2cqi,5px)/1 ui-monospace,monospace}._3723UG_previewFooter,._3723UG_previewInsight{z-index:1;width:100%;color:var(--office-muted);text-overflow:ellipsis;white-space:nowrap;margin-top:4px;font-size:clamp(2px,2.3cqi,5px);line-height:1.15;display:block;position:relative;overflow:hidden}._3723UG_previewChart{z-index:1;border-bottom:1px solid color-mix(in srgb, var(--office-muted) 34%, transparent);align-items:flex-end;gap:7%;height:43%;margin-top:auto;padding:4% 5% 0;display:flex;position:relative}._3723UG_previewChart i{background:var(--office-accent);border-radius:2px 2px 0 0;width:11%}._3723UG_previewChart i:first-child{opacity:.52;height:28%}._3723UG_previewChart i:nth-child(2){opacity:.64;height:46%}._3723UG_previewChart i:nth-child(3){opacity:.76;height:41%}._3723UG_previewChart i:nth-child(4){opacity:.88;height:72%}._3723UG_previewChart i:nth-child(5){height:91%}@media (prefers-reduced-motion:reduce){._3723UG_previewViewport,._3723UG_selectionPreview{transition:none}._3723UG_previewViewport>._3723UG_preview{animation:none}}";
		const tagId = "dsh-ppt/OfficePptHero.module.css";
		if (typeof document !== "undefined" && document.querySelector("style[data-plugin-css=" + JSON.stringify(tagId) + "]") === null) {
			const tag = document.createElement("style");
			tag.dataset.plugin = "dsh-ppt";
			tag.dataset.pluginCss = tagId;
			tag.textContent = css;
			document.head.appendChild(tag);
		}
		var OfficePptHero_module_css_default = {
			"categoryTabs": "_3723UG_categoryTabs",
			"modeChip": "_3723UG_modeChip",
			"modeRoot": "_3723UG_modeRoot",
			"modeRow": "_3723UG_modeRow",
			"panelState": "_3723UG_panelState",
			"preview": "_3723UG_preview",
			"previewAccent": "_3723UG_previewAccent",
			"previewChart": "_3723UG_previewChart",
			"previewEyebrow": "_3723UG_previewEyebrow",
			"previewFooter": "_3723UG_previewFooter",
			"previewImage": "_3723UG_previewImage",
			"previewInsight": "_3723UG_previewInsight",
			"previewKpis": "_3723UG_previewKpis",
			"previewReveal": "_3723UG_previewReveal",
			"previewViewport": "_3723UG_previewViewport",
			"retryButton": "_3723UG_retryButton",
			"selection": "_3723UG_selection",
			"selectionFrame": "_3723UG_selectionFrame",
			"selectionPreview": "_3723UG_selectionPreview",
			"selectionRemove": "_3723UG_selectionRemove",
			"templateCard": "_3723UG_templateCard",
			"templateError": "_3723UG_templateError",
			"templateGrid": "_3723UG_templateGrid",
			"templateName": "_3723UG_templateName",
			"templatePanel": "_3723UG_templatePanel",
			"templateSelect": "_3723UG_templateSelect",
			"templateToolbar": "_3723UG_templateToolbar",
			"templateViewport": "_3723UG_templateViewport"
		};
		//#endregion
		//#region src/client/OfficePptHero.tsx
		/** DSH PPT template chooser integrated into the blank-session composer. */
		const TEMPLATE_CATEGORIES = [
			"all",
			"strategy",
			"business",
			"consulting",
			"finance",
			"work",
			"promotion",
			"academic", "editorial"
		];
		const SELECTED_PREVIEW_ENTRY_TRANSFORM = "rotate(-3deg) scale(.92)";
		const SELECTED_PREVIEW_REST_TRANSFORM = "rotate(-3deg) scale(1)";
		const SELECTED_PREVIEW_DURATION_MS = 200;
		const TEMPLATE_LOAD_TIMEOUT_MS = 8e3;
		const FALLBACK_TEMPLATE_PREVIEW_PAGE_COUNT = 3;
		const TEMPLATE_PREVIEW_AUTOPLAY_START_MS = 420;
		const TEMPLATE_PREVIEW_AUTOPLAY_INTERVAL_MS = 900;
		const TEMPLATE_PREVIEW_WHEEL_LOCK_MS = 180;
		const TEMPLATE_DOCK_BOTTOM_PX = 12;
		const TEMPLATE_PANEL_MIN_HEIGHT_PX = 200;
		const STAGED_MODE_KEY = "\0dsh-ppt-unbound";
		function modeKey(sessionId) {
			return typeof sessionId === "string" && sessionId.trim().length > 0 ? sessionId : STAGED_MODE_KEY;
		}
		const EMPTY_STATE = {
			activeMode: null,
			loading: false,
			templates: [],
			selectedId: null,
			engaged: false,
            notice: false,
			error: ""
		};
		/** Session-keyed presentation state shared by the action tray and composer accessory. */
		var OfficePptHeroStore = class {
			states = /* @__PURE__ */ new Map();
			listeners = /* @__PURE__ */ new Map();
			snapshot(sessionId) {
				return this.states.get(modeKey(sessionId)) ?? EMPTY_STATE;
			}
			subscribe(sessionId, listener) {
				const key = modeKey(sessionId);
				const listeners = this.listeners.get(key) ?? /* @__PURE__ */ new Set();
				listeners.add(listener);
				this.listeners.set(key, listeners);
				return () => {
					listeners.delete(listener);
					if (listeners.size === 0) this.listeners.delete(key);
				};
			}
			revision(sessionId) {
				return this.revisions?.get(modeKey(sessionId)) ?? 0;
			}
			bump(sessionId) {
				this.revisions ??= /* @__PURE__ */ new Map();
				const key = modeKey(sessionId);
				this.revisions.set(key, (this.revisions.get(key) ?? 0) + 1);
			}
			setMode(sessionId, activeMode) {
				this.bump(sessionId);
				this.update(sessionId, (current) => ({
					...current,
					activeMode,
					engaged: true,
					error: ""
				}));
			}
			setLoading(sessionId, loading) {
				this.update(sessionId, (current) => ({
					...current,
					loading,
					error: loading ? "" : current.error
				}));
			}
			setNotice(sessionId, notice) {
                this.update(sessionId, current => ({ ...current, notice }));
            }
            setError(sessionId, error) {
				this.update(sessionId, (current) => ({
					...current,
					loading: false,
					error
				}));
			}
			setTemplateState(sessionId, next) {
                this.update(sessionId, current => ({
                    ...current,
                    templates: next.templates,
                    selectedId: next.templates.some(template => template.id === next.selectedTemplateId) ? next.selectedTemplateId : null,
                    activeMode: next.presentationMode ?? current.activeMode,
                    notice: next.templateMigration?.reason ?? null,
                    loading: false,
                    error: ""
                }));
            }
			setTemplates(sessionId, templates) {
				this.update(sessionId, (current) => ({
					...current,
					loading: false,
					templates,
					selectedId: templates.some((template) => template.id === current.selectedId) ? current.selectedId : null,
					error: ""
				}));
			}
			select(sessionId, template, activeMode) {
				this.bump(sessionId);
				this.update(sessionId, (current) => ({
					...current,
					activeMode,
					loading: false,
					selectedId: template.id,
					engaged: true,
                    notice: false,
					error: ""
				}));
			}
			deselect(sessionId, activeMode) {
				this.bump(sessionId);
				this.update(sessionId, (current) => ({
					...current,
					activeMode,
					loading: false,
					selectedId: null,
					engaged: true,
					error: ""
				}));
			}
			update(sessionId, transform) {
				const key = modeKey(sessionId);
				this.states.set(key, transform(this.states.get(key) ?? EMPTY_STATE));
				this.notify(key);
			}
			notify(sessionId) {
				for (const listener of this.listeners.get(sessionId) ?? []) listener();
			}
			clearStaged() {
				if (!this.states.has(STAGED_MODE_KEY)) return;
				this.states.delete(STAGED_MODE_KEY);
				this.notify(STAGED_MODE_KEY);
			}
			adopt(sessionId, client) {
				this.inflight ??= /* @__PURE__ */ new Map();
				this.adopted ??= /* @__PURE__ */ new Set();
				if (!client?.bound || typeof sessionId !== "string" || sessionId.trim().length === 0) return Promise.resolve("idle");
				const pending = this.inflight.get(sessionId);
				if (pending) return pending;
				if (this.adopted.has(sessionId)) return Promise.resolve("done");
				const staged = this.states.get(STAGED_MODE_KEY);
				if (!staged?.engaged) {
					this.adopted.add(sessionId);
					return Promise.resolve("idle");
				}
				const work = this.applyStaged(sessionId, client, staged).finally(() => {
					if (this.inflight.get(sessionId) === work) this.inflight.delete(sessionId);
				});
				this.inflight.set(sessionId, work);
				return work;
			}
			async applyStaged(sessionId, client, staged) {
				if (staged.activeMode !== "ppt") {
					this.clearStaged();
					this.adopted.add(sessionId);
					return "idle";
				}
				this.bump(sessionId);
				this.update(sessionId, () => ({ ...staged, loading: true, error: "" }));
				try {
					const remote = await client.call("state");
					const occupied = remote?.presentationMode === "ppt" || remote?.documentMode === "word" || remote?.documentMode === "excel" || typeof remote?.selectedTemplateId === "string";
					if (occupied) {
						this.clearStaged();
						this.update(sessionId, (current) => ({
							...current,
							templates: Array.isArray(remote?.templates) ? remote.templates : current.templates,
							selectedId: typeof remote?.selectedTemplateId === "string" ? remote.selectedTemplateId : null,
							activeMode: remote?.presentationMode === "ppt" ? "ppt" : null,
							loading: false,
							engaged: false,
							error: ""
						}));
						this.adopted.add(sessionId);
						return "kept";
					}
					if (staged.selectedId) {
						try {
							await client.call("template/select", { templateId: staged.selectedId, mode: "ppt" });
						} catch (reason) {
							await client.call("presentation/mode", { mode: "ppt" });
							this.update(sessionId, (current) => ({
								...current,
								activeMode: "ppt",
								selectedId: null,
								loading: false,
								engaged: true,
								error: reason instanceof Error ? reason.message : String(reason)
							}));
							this.clearStaged();
							this.adopted.add(sessionId);
							return "partial";
						}
					} else if (staged.activeMode === "ppt") {
						await client.call("presentation/mode", { mode: "ppt" });
					}
					const next = await client.call("state");
					this.setTemplateState(sessionId, next);
					this.clearStaged();
					this.adopted.add(sessionId);
					return "applied";
				} catch (reason) {
					this.update(sessionId, (current) => ({
						...current,
						loading: false,
						engaged: true,
						error: reason instanceof Error ? reason.message : String(reason)
					}));
					this.clearStaged();
					this.adopted.add(sessionId);
					return "failed";
				}
			}
			applyLoadedTemplates(sessionId, client, seenRevision, next, request) {
				if (request != null && (request.client !== client || modeKey(request.sessionId) !== modeKey(sessionId))) return false;
				if (this.revision(sessionId) !== seenRevision) return false;
				const activeMode = this.snapshot(sessionId).activeMode ?? (next?.presentationMode === "ppt" ? "ppt" : null);
				this.setTemplates(sessionId, next?.templates ?? []);
				if (!client?.bound || activeMode === null) return true;
				this.setMode(sessionId, activeMode);
				this.setNotice(sessionId, next?.templateMigration?.reason ?? null);
				const selected = (next?.templates ?? []).find((template) => template.id === next.selectedTemplateId && (template.supportedModes?.includes("ppt") ?? true));
				if (selected === void 0) {
					this.deselect(sessionId, activeMode);
					return true;
				}
				this.select(sessionId, selected, activeMode);
				return true;
			}
		};
		function useMode(mode, sessionId) {
			return (0, react.useSyncExternalStore)((listener) => mode.subscribe(sessionId, listener), () => mode.snapshot(sessionId), () => mode.snapshot(sessionId));
		}
		function templateStyle(template) {
			return {
				"--office-bg": `#${template.palette.background}`,
				"--office-surface": `#${template.palette.surface}`,
				"--office-text": `#${template.palette.text}`,
				"--office-muted": `#${template.palette.muted}`,
				"--office-accent": `#${template.palette.accent}`,
				"--office-secondary": `#${template.palette.secondary}`
			};
		}
		function templateCategory(template) {
            if (template.origin === "personal") return "personal";
			if (template.origin === "extracted") return "custom";
			return template.category ?? "business";
		}
		function templateVariant(template) {
			return template.source?.visualGrammar ?? "custom";
		}
		function templatePreviewPages(template) {
			return (template.previewImages ?? CURATED_TEMPLATE_PREVIEWS[template.id])?.length ?? FALLBACK_TEMPLATE_PREVIEW_PAGE_COUNT;
		}
		function TemplatePreview({ template, page = 0 }) {
			const previewImage = (template.previewImages ?? CURATED_TEMPLATE_PREVIEWS[template.id])?.[page];
			return /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", {
				className: OfficePptHero_module_css_default.preview,
				"data-page": page,
				"data-source-preview": previewImage === void 0 ? void 0 : true,
				"data-variant": templateVariant(template),
				style: templateStyle(template),
				children: [previewImage !== void 0 && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("img", {
					className: OfficePptHero_module_css_default.previewImage,
					src: previewImage,
					draggable: false,
					loading: "lazy",
					decoding: "async",
					alt: "",
					"aria-hidden": "true"
				}), previewImage === void 0 && /* @__PURE__ */ (0, react_jsx_runtime.jsxs)(react_jsx_runtime.Fragment, { children: [
					/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", { className: OfficePptHero_module_css_default.previewAccent }),
					page === 0 && /* @__PURE__ */ (0, react_jsx_runtime.jsxs)(react_jsx_runtime.Fragment, { children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("strong", { children: template.previewTitle }), /* @__PURE__ */ (0, react_jsx_runtime.jsx)("small", { children: template.previewSubtitle })] }),
					page === 1 && /* @__PURE__ */ (0, react_jsx_runtime.jsxs)(react_jsx_runtime.Fragment, { children: [
						/* @__PURE__ */ (0, react_jsx_runtime.jsx)("small", {
							className: OfficePptHero_module_css_default.previewEyebrow,
							children: template.previewSubtitle
						}),
						/* @__PURE__ */ (0, react_jsx_runtime.jsx)("strong", { children: template.previewTitle }),
						/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", {
							className: OfficePptHero_module_css_default.previewKpis,
							"aria-hidden": "true",
							children: [
								/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", { children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("b", { children: "32%" }), /* @__PURE__ */ (0, react_jsx_runtime.jsx)("i", { children: "01" })] }),
								/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", { children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("b", { children: "18.6" }), /* @__PURE__ */ (0, react_jsx_runtime.jsx)("i", { children: "02" })] }),
								/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", { children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("b", { children: "04" }), /* @__PURE__ */ (0, react_jsx_runtime.jsx)("i", { children: "03" })] })
							]
						}),
						/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
							className: OfficePptHero_module_css_default.previewFooter,
							children: template.description
						})
					] }),
					page === 2 && /* @__PURE__ */ (0, react_jsx_runtime.jsxs)(react_jsx_runtime.Fragment, { children: [
						/* @__PURE__ */ (0, react_jsx_runtime.jsx)("small", {
							className: OfficePptHero_module_css_default.previewEyebrow,
							children: template.previewSubtitle
						}),
						/* @__PURE__ */ (0, react_jsx_runtime.jsx)("strong", { children: template.previewTitle }),
						/* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", {
							className: OfficePptHero_module_css_default.previewChart,
							"aria-hidden": "true",
							children: [
								/* @__PURE__ */ (0, react_jsx_runtime.jsx)("i", {}),
								/* @__PURE__ */ (0, react_jsx_runtime.jsx)("i", {}),
								/* @__PURE__ */ (0, react_jsx_runtime.jsx)("i", {}),
								/* @__PURE__ */ (0, react_jsx_runtime.jsx)("i", {}),
								/* @__PURE__ */ (0, react_jsx_runtime.jsx)("i", {})
							]
						}),
						/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
							className: OfficePptHero_module_css_default.previewInsight,
							children: template.description
						})
					] })
				] })]
			});
		}
		function TemplatePreviewDeck({ template, page }) {
			return /* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
				className: OfficePptHero_module_css_default.previewViewport,
				children: /* @__PURE__ */ (0, react_jsx_runtime.jsx)(TemplatePreview, {
					template,
					page
				}, page)
			});
		}
		function TemplateCard({ template, selected, choose }) {
			const [page, setPage] = (0, react.useState)(0);
			const [hovered, setHovered] = (0, react.useState)(false);
			const card = (0, react.useRef)(null);
			const hoveredCard = (0, react.useRef)(false);
			const lastWheelAt = (0, react.useRef)(Number.NEGATIVE_INFINITY);
			const pageCount = templatePreviewPages(template);
			(0, react.useEffect)(() => {
				if (!hovered || pageCount <= 1 || reducedMotionPreferred()) return;
				const advance = () => {
					if (!hoveredCard.current || document.visibilityState === "hidden") return;
					if (performance.now() - lastWheelAt.current < TEMPLATE_PREVIEW_AUTOPLAY_INTERVAL_MS) return;
					setPage((current) => (current + 1) % pageCount);
				};
				let interval;
				const start = window.setTimeout(() => {
					advance();
					interval = window.setInterval(advance, TEMPLATE_PREVIEW_AUTOPLAY_INTERVAL_MS);
				}, TEMPLATE_PREVIEW_AUTOPLAY_START_MS);
				return () => {
					window.clearTimeout(start);
					if (interval !== void 0) window.clearInterval(interval);
				};
			}, [hovered, pageCount]);
			(0, react.useEffect)(() => {
				const element = card.current;
				if (!hovered || element === null) return;
				const stopOutsideCard = (event) => {
					if (event.target instanceof Node && element.contains(event.target)) return;
					hoveredCard.current = false;
					setHovered(false);
					setPage(0);
					lastWheelAt.current = Number.NEGATIVE_INFINITY;
				};
				document.addEventListener("mousemove", stopOutsideCard, true);
				return () => {
					document.removeEventListener("mousemove", stopOutsideCard, true);
				};
			}, [hovered]);
			(0, react.useEffect)(() => {
				const element = card.current;
				if (element === null || pageCount <= 1) return;
				const pageWithWheel = (event) => {
					const horizontalDistance = Math.abs(event.deltaX);
					const verticalDistance = Math.abs(event.deltaY);
					if (horizontalDistance < 4 || horizontalDistance < verticalDistance * .65) return;
					const delta = event.deltaX;
					if (!Number.isFinite(delta) || delta === 0) return;
					event.preventDefault();
					const now = performance.now();
					if (now - lastWheelAt.current < TEMPLATE_PREVIEW_WHEEL_LOCK_MS) return;
					lastWheelAt.current = now;
					setPage((current) => (current + (delta > 0 ? 1 : -1) + pageCount) % pageCount);
				};
				element.addEventListener("wheel", pageWithWheel, { passive: false });
				return () => {
					element.removeEventListener("wheel", pageWithWheel);
				};
			}, [pageCount]);
			return /* @__PURE__ */ (0, react_jsx_runtime.jsx)("article", {
				ref: card,
				className: OfficePptHero_module_css_default.templateCard,
				"data-selected": selected || void 0,
				onMouseEnter: () => {
					hoveredCard.current = true;
					setHovered(true);
				},
				onMouseLeave: () => {
					hoveredCard.current = false;
					setHovered(false);
					setPage(0);
					lastWheelAt.current = Number.NEGATIVE_INFINITY;
				},
				children: /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("button", {
					type: "button",
					className: OfficePptHero_module_css_default.templateSelect,
					"aria-label": template.name,
					"aria-pressed": selected,
					onClick: () => {
						choose(template);
					},
					children: [
						/* @__PURE__ */ (0, react_jsx_runtime.jsx)(TemplatePreviewDeck, {
							template,
							page
						}),
						/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
							className: OfficePptHero_module_css_default.templateName,
							title: template.name,
							children: template.name
						})
					]
				})
			});
		}
		function reducedMotionPreferred() {
			return typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
		}
		function loadTemplateState(client, timeoutMessage) {
			const controller = new AbortController();
			return new Promise((resolve, reject) => {
				const timer = window.setTimeout(() => {
					controller.abort();
					reject(new Error(timeoutMessage));
				}, TEMPLATE_LOAD_TIMEOUT_MS);
				client.call("state", {}, controller.signal).then((next) => {
					window.clearTimeout(timer);
					resolve(next);
				}, (reason) => {
					window.clearTimeout(timer);
					reject(reason instanceof Error ? reason : new Error(String(reason)));
				});
			});
		}
		function deselectTemplate(client, mode, sessionId, activeMode) {
            mode.bump(sessionId);
            const revision = mode.revision(sessionId);
			mode.setLoading(sessionId, true);
			if (!client.bound) {
				mode.deselect(sessionId, activeMode);
                announcePptMode(sessionId);
				return;
			}
			client.call("template/deselect").then(() => {
                if (mode.revision(sessionId) !== revision) return;
				return client.call("presentation/mode", { mode: activeMode });
			}).then(() => {
                if (mode.revision(sessionId) !== revision) return;
                announcePptMode(sessionId);
				mode.deselect(sessionId, activeMode);
			}).catch((reason) => {
                if (mode.revision(sessionId) === revision) mode.setError(sessionId, reason instanceof Error ? reason.message : String(reason));
			});
		}
        function announcePptMode(sessionId) {
            window.dispatchEvent(new CustomEvent('dsh-office-mode-change', { detail: { sessionId, origin: 'ppt' } }));
        }
		function selectPresentationMode(client, mode, sessionId, activeMode) {
            if (!client.bound) { mode.setMode(sessionId, activeMode); announcePptMode(sessionId); return; }
            mode.bump(sessionId);
            const revision = mode.revision(sessionId);
            mode.setLoading(sessionId, true);
            client.call("presentation/mode", { mode: activeMode }).then(() => {
                if (mode.revision(sessionId) !== revision) return;
                announcePptMode(sessionId);
                mode.setMode(sessionId, activeMode);
                mode.setLoading(sessionId, false);
            }).catch((reason) => {
                if (mode.revision(sessionId) === revision) mode.setError(sessionId, reason instanceof Error ? reason.message : String(reason));
            });
        }
		/** Compact selected-template thumbnail inside the resident input card. */
		function OfficePptInputAccessory({ client, mode, sessionId, t }) {
			const state = useMode(mode, sessionId);
			const selected = state.templates.find((template) => template.id === state.selectedId);
			const selectedId = state.activeMode !== null && selected !== void 0 ? selected.id : null;
			const preview = (0, react.useRef)(null);
			const frame = (0, react.useRef)(null);
			const settleTimer = (0, react.useRef)(null);
			const previousId = (0, react.useRef)(selectedId);
			(0, react.useLayoutEffect)(() => {
				if (selectedId === null) {
					if (frame.current !== null) window.cancelAnimationFrame(frame.current);
					if (settleTimer.current !== null) window.clearTimeout(settleTimer.current);
					frame.current = null;
					settleTimer.current = null;
					previousId.current = null;
					return;
				}
				if (previousId.current === selectedId || preview.current === null) return;
				previousId.current = selectedId;
				const element = preview.current;
				const from = frame.current !== null || settleTimer.current !== null ? window.getComputedStyle(element).transform : SELECTED_PREVIEW_ENTRY_TRANSFORM;
				if (frame.current !== null) window.cancelAnimationFrame(frame.current);
				if (settleTimer.current !== null) window.clearTimeout(settleTimer.current);
				frame.current = null;
				settleTimer.current = null;
				element.style.transition = "none";
				element.style.transform = from;
				if (reducedMotionPreferred()) {
					element.style.removeProperty("transition");
					element.style.removeProperty("transform");
					return;
				}
				element.getBoundingClientRect();
				const settle = () => {
					element.style.removeProperty("transition");
					element.style.transform = SELECTED_PREVIEW_REST_TRANSFORM;
					frame.current = null;
					settleTimer.current = window.setTimeout(() => {
						element.style.removeProperty("transform");
						settleTimer.current = null;
					}, SELECTED_PREVIEW_DURATION_MS);
				};
				if (typeof window.requestAnimationFrame === "function") frame.current = window.requestAnimationFrame(settle);
				else settle();
			}, [selectedId]);
			(0, react.useEffect)(() => () => {
				if (frame.current !== null) window.cancelAnimationFrame(frame.current);
				if (settleTimer.current !== null) window.clearTimeout(settleTimer.current);
			}, []);
			if (state.activeMode === null || selected === void 0) return null;
			const activeMode = state.activeMode;
			return /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
				className: OfficePptHero_module_css_default.selection,
				"aria-label": `${t("composer.selectedTemplate")}: ${selected.name}`,
				children: /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("span", {
					ref: preview,
					className: OfficePptHero_module_css_default.selectionPreview,
					children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", {
						className: OfficePptHero_module_css_default.selectionFrame,
						children: /* @__PURE__ */ (0, react_jsx_runtime.jsx)(TemplatePreview, { template: selected })
					}), /* @__PURE__ */ (0, react_jsx_runtime.jsx)("button", {
						type: "button",
						className: OfficePptHero_module_css_default.selectionRemove,
						"aria-label": t("composer.removeTemplate"),
						onClick: () => {
							deselectTemplate(client, mode, sessionId, activeMode);
						},
						children: "×"
					})]
				})
			});
		}
		/** Selected-template reference shown only while the standard Session is blank. */
		function OfficePptStandardInputAccessory(props) {
			if (props.session == null || !props.session.blank) return null;
			return /* @__PURE__ */ (0, react_jsx_runtime.jsx)(OfficePptInputAccessory, { ...props });
		}
		/** PPT option and template chooser shared by both Composer layouts. */
		/* PERSONAL_TEMPLATE_MANAGER */
		function OfficePptChooser({ client, mode, sessionId, t, placement, loadTemplates = true }) {
			const state = useMode(mode, sessionId);
			const modeRootRef = (0, react.useRef)(null);
			const templatePanelRef = (0, react.useRef)(null);
			const templateViewportRef = (0, react.useRef)(null);
			const [category, setCategory] = (0, react.useState)("all");
			const bindingRef = (0, react.useRef)({ client, sessionId });
			bindingRef.current = { client, sessionId };
			const catalogRevision = mode.revision(sessionId);
			(0, react.useEffect)(() => {
				if (!loadTemplates || state.templates.length > 0 || state.error !== "") return;
				const request = { client, sessionId };
				const seenRevision = catalogRevision;
				mode.setLoading(sessionId, true);
				let active = true;
				loadTemplateState(client, t("templates.loadTimeout")).then((next) => {
					if (!active) return;
					const current = bindingRef.current;
					mode.applyLoadedTemplates(current.sessionId, current.client, seenRevision, next, request);
				}).catch((reason) => {
					if (!active) return;
					const current = bindingRef.current;
					if (current.client !== request.client || modeKey(current.sessionId) !== modeKey(request.sessionId)) return;
					if (mode.revision(request.sessionId) !== seenRevision) return;
					mode.setError(request.sessionId, reason instanceof Error ? reason.message : String(reason));
				});
				return () => {
					active = false;
				};
				// loading is not a dependency: setLoading would cancel this request.
				// catalogRevision is: a mode click invalidates the response, so the effect loads again.
			}, [
				catalogRevision,
				client,
				loadTemplates,
				mode,
				sessionId,
				state.error,
				state.templates.length,
				t
			]);
			const deselect = () => {
				deselectTemplate(client, mode, sessionId, state.activeMode ?? "ppt");
			};
			const select = (template, activeMode = state.activeMode ?? "ppt") => {
				if (!client.bound) {
					mode.select(sessionId, template, activeMode);
                    announcePptMode(sessionId);
					return;
				}
                mode.bump(sessionId);
                const revision = mode.revision(sessionId);
				mode.setLoading(sessionId, true);
				client.call("template/select", {
					templateId: template.id,
					mode: activeMode
				}).then(() => {
                    if (mode.revision(sessionId) !== revision) return;
                    announcePptMode(sessionId);
					mode.select(sessionId, template, activeMode);
				}).catch((reason) => {
					if (mode.revision(sessionId) === revision) mode.setError(sessionId, reason instanceof Error ? reason.message : String(reason));
				});
			};
			const choose = (template) => {
				if (template.id === state.selectedId) {
					deselect();
					return;
				}
				select(template);
			};
			const togglePpt = () => {
				if (state.activeMode === "ppt") {
					selectPresentationMode(client, mode, sessionId, null);
					return;
				}
				const selected = state.templates.find((template) => template.id === state.selectedId && templateSupportsMode(template, "ppt"));
				if (selected === void 0) {
					if (state.selectedId !== null) {
						deselectTemplate(client, mode, sessionId, "ppt");
						return;
					}
					selectPresentationMode(client, mode, sessionId, "ppt");
					return;
				}
				select(selected, "ppt");
			};
			const modeTemplates = state.templates.filter((template) => templateSupportsMode(template, "ppt"));
			const templateCategories = ["all", ...new Set(modeTemplates.filter(item => item.origin !== "personal").map(templateCategory)), "personal"];
			const visibleTemplates = modeTemplates.filter((template) => category === "all" ? template.origin !== "personal" : templateCategory(template) === category);
			(0, react.useEffect)(() => {
				if (!templateCategories.includes(category)) setCategory("all");
			}, [category, templateCategories]);
			(0, react.useLayoutEffect)(() => {
				if (placement === "trigger") return;
				const root = modeRootRef.current;
				const panel = templatePanelRef.current;
				if (state.activeMode === null || root === null || panel === null) return;
				const scrollBody = root.closest("[data-conversation-scroll]");
				const composerCard = root.closest("[data-composer-seat]")?.querySelector("[data-composer-card]") ?? null;
				if (scrollBody === null || composerCard === null) return;
				const syncGeometry = () => {
					const scrollRect = scrollBody.getBoundingClientRect();
					const panelRect = panel.getBoundingClientRect();
					const availableHeight = Math.max(TEMPLATE_PANEL_MIN_HEIGHT_PX, Math.floor(scrollRect.bottom - panelRect.top - TEMPLATE_DOCK_BOTTOM_PX));
					root.style.setProperty("--office-ppt-template-panel-height", `${availableHeight}px`);
				};
				const resizeObserver = typeof ResizeObserver === "function" ? new ResizeObserver(syncGeometry) : null;
				resizeObserver?.observe(scrollBody);
				resizeObserver?.observe(composerCard);
				window.addEventListener("resize", syncGeometry);
				const frame = window.requestAnimationFrame(syncGeometry);
				return () => {
					window.cancelAnimationFrame(frame);
					resizeObserver?.disconnect();
					window.removeEventListener("resize", syncGeometry);
					root.style.removeProperty("--office-ppt-template-panel-height");
				};
			}, [placement, state.activeMode]);
			if (placement === "trigger") return /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("button", {
				type: "button",
				className: OfficePptHero_module_css_default.modeChip,
				"data-selected": state.activeMode === "ppt" || void 0,
				"aria-expanded": state.activeMode === "ppt",
				onClick: togglePpt,
				children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)(_deepseek_ai_dsh_client_ui_primitives.IconBrowseOutline16, { size: 15 }), t("mode.label")]
			});
			if (placement === "fixed" && state.activeMode === null) return null;
			return /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("section", {
				ref: modeRootRef,
				className: OfficePptHero_module_css_default.modeRoot,
				"data-placement": placement,
				"aria-label": t("mode.region"),
				children: [placement === "overlay" && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
					className: OfficePptHero_module_css_default.modeRow,
					children: /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("button", {
						type: "button",
						className: OfficePptHero_module_css_default.modeChip,
						"data-selected": state.activeMode === "ppt" || void 0,
						"aria-expanded": state.activeMode === "ppt",
						onClick: togglePpt,
						children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)(_deepseek_ai_dsh_client_ui_primitives.IconBrowseOutline16, { size: 15 }), t("mode.label")]
					})
				}), state.activeMode !== null && /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
					ref: templatePanelRef,
					className: OfficePptHero_module_css_default.templatePanel,
					"data-office-ppt-template-panel": "",
					children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
						className: OfficePptHero_module_css_default.templateToolbar,
						children: /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
							className: OfficePptHero_module_css_default.categoryTabs,
							role: "tablist",
							"aria-label": t("templates.categories"),
							children: templateCategories.map((item) => /* @__PURE__ */ (0, react_jsx_runtime.jsx)("button", {
								type: "button",
								role: "tab",
								"aria-selected": category === item,
								"data-selected": category === item || void 0,
								onClick: () => {
									setCategory(item);
								},
								children: t(`templates.category.${item}`)
							}, item))
						})
					}), /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
						ref: templateViewportRef,
						className: OfficePptHero_module_css_default.templateViewport,
						"data-office-ppt-template-viewport": "",
						"data-native-wheel-owner": "",
						children: [(category === "all" || category === "personal") && react.createElement(PersonalTemplateManager, { key: sessionId, client, mode, sessionId, state, choose, t, mutable: client.bound === true, builtInCards: category === "all" ? visibleTemplates.map(template => react.createElement(TemplatePreviewCard, { key: template.id, template, selected: template.id === state.selectedId, choose, client, t })) : [] }), state.error !== "" && state.templates.length > 0 && /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
							className: OfficePptHero_module_css_default.templateError,
							role: "alert",
							children: state.error
						}), (category === "all" || category === "personal") ? null : state.loading && state.templates.length === 0 ? /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
							className: OfficePptHero_module_css_default.panelState,
							children: t("status.loading")
						}) : state.error !== "" && state.templates.length === 0 ? /* @__PURE__ */ (0, react_jsx_runtime.jsxs)("div", {
							className: OfficePptHero_module_css_default.panelState,
							role: "alert",
							children: [/* @__PURE__ */ (0, react_jsx_runtime.jsx)("span", { children: state.error }), /* @__PURE__ */ (0, react_jsx_runtime.jsx)("button", {
								type: "button",
								className: OfficePptHero_module_css_default.retryButton,
								onClick: () => {
									mode.setError(sessionId, "");
								},
								children: t("templates.retry")
							})]
						}) : visibleTemplates.length === 0 ? /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
							className: OfficePptHero_module_css_default.panelState,
							children: t("templates.empty")
						}) : /* @__PURE__ */ (0, react_jsx_runtime.jsx)("div", {
							className: OfficePptHero_module_css_default.templateGrid,
							children: visibleTemplates.map((template) => /* @__PURE__ */ (0, react_jsx_runtime.jsx)(TemplatePreviewCard, {
                                client, t,
								template,
								selected: template.id === state.selectedId,
								choose
							}, template.id))
						})]
					})]
				})]
			});
		}
		/** Standard Composer chooser rendered in normal flow below the resident input card. */
		function OfficePptStandardComposerDock(props) {
			if (props.session != null && props.session.blank !== true) return null;
			return /* @__PURE__ */ (0, react_jsx_runtime.jsx)(OfficePptChooser, {
				...props,
				placement: "fixed",
				loadTemplates: false
			});
		}
		/** PPT mode control beside the blank-session agent preset. */
		function OfficePptStandardModeAction(props) {
            const state = useMode(props.mode, props.sessionId);
            (0, react.useEffect)(() => {
                if (!props.client?.bound) return;
                props.mode.adopt(props.sessionId, props.client);
            }, [props.client, props.mode, props.sessionId]);
            return (0, react_jsx_runtime.jsxs)(react.Fragment, { children: [
                (0, react_jsx_runtime.jsx)(OfficePptChooser, { ...props, placement: "trigger" }),
                state.notice && state.activeMode !== null ? (0, react_jsx_runtime.jsx)("span", {
                    role: "status", "data-ppt-template-migration": "",
                    style: { fontSize: 11, color: "var(--dsw-alias-label-secondary)", maxWidth: 300 },
                    children: props.t(state.notice === "personal-template-deleted" ? "personal.deletedSelection" : "templates.migrated")
                }) : null
            ] });
        }
		//#endregion
		//#region src/client/locales.ts
		/** Office PPT composer-mode dictionaries. */
		/** Locale namespace. */
		const NS = "dsh-ppt";
		/** Simplified Chinese dictionary. */
		const zh = {
			"mode.label": "PPT",
			"mode.region": "演示文稿模式",
			"composer.selectedTemplate": "已选模板",
			"composer.removeTemplate": "取消选择模板",
			"templates.title": "选择模板",
            "templates.migrated": "原模板已下架，已切换为工程蓝图。已有文件不受影响。",
			"templates.categories": "模板分类",
			"templates.empty": "该分类下还没有模板",
			"templates.loadTimeout": "模板加载超时，请重试",
			"templates.retry": "重新加载模板",
			"templates.category.all": "全部",
"templates.category.personal": "自定义",
"personal.deletedSelection": "已选个人模板已被删除，请重新选择。",
"personal.upload": "上传 PPT 模板",
"personal.create": "新建自定义模板",
"personal.selected": "已选中",
"personal.local": "保存在当前 Desktop · PPTX",
"personal.fileType": "请选择 PPTX 文件",
"personal.readFailed": "文件读取失败，请重新选择",
"personal.duplicate": "这份文件已在我的模板中，可直接选择使用",
"personal.useSame": "做同款",
"personal.view": "预览",
"personal.zoomIn": "放大",
"personal.zoomOut": "缩小",
"personal.fit": "适应窗口",
"personal.previewFailed": "预览加载失败，请重试",
"personal.processing": "正在处理模板…",
"personal.completedPages": "已完成",
"personal.placeholderNotice": "部分对象已使用占位图，可在 PPT 中替换。",
"personal.layouts": "版式",
"personal.chooseFile": "重新选择 PPT",
"personal.preview": "模板预览",
"personal.name": "模板名称",
"personal.previous": "上一页",
"personal.next": "下一页",
"personal.save": "保存模板",
"personal.saved": "模板已保存",
"personal.cancel": "取消",
"personal.edit": "编辑模板",
"personal.editTitle": "编辑自定义模板",
"personal.description": "模板描述",
"personal.descriptionPlaceholder": "描述模板的风格或适用场景（选填）",
"personal.update": "保存修改",
"personal.close": "关闭",
"personal.deleteTitle": "删除模板",
"personal.rename": "重命名",
"personal.delete": "删除",
"personal.deleteHint": "删除模板后，已生成的文件继续保留。",
"personal.confirmDelete": "确认删除",
			"templates.category.custom": "自定义",
			"templates.category.business": "商务",
			"templates.category.strategy": "策略",
			"templates.category.consulting": "咨询",
			"templates.category.finance": "金融",
			"templates.category.work": "工作",
			"templates.category.promotion": "推广",
			"templates.category.academic": "学术",
			"templates.category.data": "数据",
			"templates.category.editorial": "编辑",
			"templates.category.briefing": "简报",
			"status.loading": "正在处理…",
			"tool.structure": "PPT 结构",
			"tool.structure.open": "查看第 {page} 页：{title}",
			"tool.pages": "页",
			"tool.inspect": "详情",
			"tool.plan": "PPT 规划与校验",
			"tool.plan.story": "叙事",
			"tool.plan.layouts": "种版式",
			"tool.plan.qa": "页面",
			"tool.preview": "PPT 预览",
			"tool.preview.loading": "正在读取最终版本…",
			"tool.preview.failed": "最终版本读取失败",
			"tool.preview.previous": "上一页",
			"tool.preview.next": "下一页",
			"tool.preview.slide": "第 {page} 页，共 {total} 页",
			"tool.preview.retry": "重试",
			"tool.preview.revision": "只读 · 修订版 {revision}",
			"tool.preview.rendering": "正在渲染最终 PPTX…",
			"tool.preview.structure": "内容结构预览",
			"tool.preview.structureOnly": "当前显示内容结构，打开 PPT 可查看最终样式。",
			"tool.preview.structureFailed": "最终 PPTX 渲染失败，当前显示内容结构。",
			"tool.preview.structureLarge": "文件超过在线预览大小上限，当前显示内容结构。",
			"tool.artifact": "PPT 产出物",
			"tool.artifact.saved": "已保存到当前工作区",
			"tool.artifact.fallback": "可编辑演示文稿.pptx",
			"tool.download": "下载 PPTX",
			"tool.openFile": "打开 PPT",
			"tool.openFolder": "在 Finder 中显示",
			"tool.downloading": "正在下载…",
			"tool.openingFile": "正在打开…",
			"tool.openingFolder": "正在打开…",
			"tool.fileActionFailed": "文件操作失败，请重试",
			"tool.create.running": "正在生成 PPT",
			"tool.create.done": "PPT 已生成",
			"tool.create.failed": "PPT 生成失败",
			"tool.update.running": "正在修改第 {page} 页",
			"tool.update.done": "第 {page} 页已更新",
			"tool.update.failed": "第 {page} 页修改失败",
			"tool.update.content": "页面内容已更新"
		};
		/** English dictionary. */
		const en = {
			"mode.label": "PPT",
			"mode.region": "Presentation modes",
			"composer.selectedTemplate": "Selected template",
			"composer.removeTemplate": "Remove selected template",
			"templates.title": "Select template",
            "templates.migrated": "The previous template was retired. Engineering Blueprint is selected; existing files are unchanged.",
			"templates.categories": "Template categories",
			"templates.empty": "No templates in this category",
			"templates.loadTimeout": "Template loading timed out. Try again.",
			"templates.retry": "Reload templates",
			"templates.category.all": "All",
"templates.category.personal": "Custom",
"personal.deletedSelection": "The selected personal template was deleted. Choose another template.",
"personal.upload": "Upload PPT template",
"personal.create": "Create custom template",
"personal.selected": "Selected",
"personal.local": "Saved in this Desktop profile · PPTX",
"personal.fileType": "Choose a PPTX file",
"personal.readFailed": "Could not read the file. Choose it again.",
"personal.duplicate": "This file is already in My templates. Select it to reuse it.",
"personal.useSame": "Use this template",
"personal.view": "Preview",
"personal.zoomIn": "Zoom in",
"personal.zoomOut": "Zoom out",
"personal.fit": "Fit to window",
"personal.previewFailed": "Could not load preview. Please retry.",
"personal.processing": "Processing template…",
"personal.completedPages": "Completed",
"personal.placeholderNotice": "Some objects use placeholders. You can replace them in the PPT.",
"personal.layouts": "Layouts",
"personal.chooseFile": "Choose another PPT",
"personal.preview": "Template preview",
"personal.name": "Template name",
"personal.previous": "Previous page",
"personal.next": "Next page",
"personal.save": "Save template",
"personal.saved": "Template saved",
"personal.cancel": "Cancel",
"personal.edit": "Edit template",
"personal.editTitle": "Edit custom template",
"personal.description": "Template description",
"personal.descriptionPlaceholder": "Describe its style or use cases (optional)",
"personal.update": "Save changes",
"personal.close": "Close",
"personal.deleteTitle": "Delete template",
"personal.rename": "Rename",
"personal.delete": "Delete",
"personal.deleteHint": "Generated files are preserved when you delete a template.",
"personal.confirmDelete": "Confirm delete",
			"templates.category.custom": "Custom",
			"templates.category.business": "Business",
			"templates.category.strategy": "Strategy",
			"templates.category.consulting": "Consulting",
			"templates.category.finance": "Finance",
			"templates.category.work": "Work",
			"templates.category.promotion": "Promotion",
			"templates.category.academic": "Academic",
			"templates.category.data": "Data",
			"templates.category.editorial": "Editorial",
			"templates.category.briefing": "Briefing",
			"status.loading": "Processing…",
			"tool.structure": "Presentation structure",
			"tool.structure.open": "View slide {page}: {title}",
			"tool.pages": "slides",
			"tool.inspect": "Details",
			"tool.plan": "Presentation planning and QA",
			"tool.plan.story": "Story",
			"tool.plan.layouts": "layouts",
			"tool.plan.qa": "Pages",
			"tool.preview": "Presentation preview",
			"tool.preview.loading": "Loading the final revision…",
			"tool.preview.failed": "Could not load the final revision",
			"tool.preview.previous": "Previous slide",
			"tool.preview.next": "Next slide",
			"tool.preview.slide": "Slide {page} of {total}",
			"tool.preview.retry": "Retry",
			"tool.preview.revision": "Read only · Revision {revision}",
			"tool.preview.rendering": "Rendering the final PPTX…",
			"tool.preview.structure": "Content structure preview",
			"tool.preview.structureOnly": "This view shows content structure. Open the PPTX for final styling.",
			"tool.preview.structureFailed": "Final PPTX rendering failed. This view shows content structure.",
			"tool.preview.structureLarge": "This file exceeds the inline preview limit. This view shows content structure.",
			"tool.artifact": "Presentation output",
			"tool.artifact.saved": "Saved in the current workspace",
			"tool.artifact.fallback": "Editable presentation.pptx",
			"tool.download": "Download PPTX",
			"tool.openFile": "Open presentation",
			"tool.openFolder": "Show in Finder",
			"tool.downloading": "Downloading…",
			"tool.openingFile": "Opening…",
			"tool.openingFolder": "Opening…",
			"tool.fileActionFailed": "File action failed. Try again.",
			"tool.create.running": "Generating presentation",
			"tool.create.done": "Presentation generated",
			"tool.create.failed": "Presentation failed",
			"tool.update.running": "Updating slide {page}",
			"tool.update.done": "Slide {page} updated",
			"tool.update.failed": "Slide {page} update failed",
			"tool.update.content": "Slide content updated"
		};
		//#endregion
		//#region src/client/rpc.ts
		/**
		* Bind every request to the active conversation session.
		* @param rpc - Browser Connection RPC client.
		* @param sessionId - Active conversation session.
		* @returns Session-bound Office PPT client.
		*/
		function createOfficePptClient(rpc, sessionId) {
			const bound = typeof sessionId === "string" && sessionId.trim().length > 0;
			return { bound, async call(endpoint, payload = {}, signal) {
				const route = !bound && (endpoint === "state" || endpoint === "template/catalog") ? "template/catalog" : endpoint;
				if (!bound && route !== "template/catalog") throw new Error("PPT session is not ready");
				const outer = await rpc.call("/dsh-ppt", route, bound ? { sessionId, ...payload } : {}, signal);
				if (!outer.ok) throw new Error(outer.error.message);
				const raw = outer.value;
				if (raw === null || typeof raw !== "object" || !("status" in raw)) throw new Error("Office PPT returned an invalid response");
				const inner = raw;
				if (inner.status === "error") throw new Error(inner.error.message);
				if (!bound && endpoint === "state") return { templates: inner.data?.templates ?? [], selectedTemplateId: null, presentationMode: null };
				return inner.data;
			} };
		}
		//#endregion
		//#region src/client/standard.ts
		/** Browser services required by the standard Composer adapter. */
		const standardInject = [
			"slots",
			"locale",
			"connection"
		];
		/** Build the session-scoped browser face shared by both Composer layouts. */
		function officePptHeroInjection(ctx) {
			ctx.effect(() => ctx.locale.register(NS, {
				zh,
				en
			}), "dsh-ppt: dictionaries");
			const connection = ctx.get("connection");
			const mode = new OfficePptHeroStore();
			return (sessionId) => ({
				client: createOfficePptClient(connection.rpc, sessionId),
				mode
			});
		}
		/**
		* Register the PPT chooser on the cross-version standard Composer seats.
		* @param ctx - Browser context that owns the standard Composer slots.
		*/
		function applyStandard(ctx) {
			const injectHero = officePptHeroInjection(ctx);
			ctx.slots.inject("conversation.hero.modeActions", () => ctx.slots.register({
				name: "conversation.hero.modeActions",
				id: "dsh-ppt",
				order: 20,
				locale: NS,
				inject: injectHero
			}, OfficePptStandardModeAction));
			ctx.slots.inject("conversation.input.accessory", () => ctx.slots.register({
				name: "conversation.input.accessory",
				id: "dsh-ppt",
				order: 20,
				locale: NS,
				inject: injectHero
			}, OfficePptStandardInputAccessory));
			ctx.slots.inject("conversation.composer.dock", () => ctx.slots.register({
				name: "conversation.composer.dock",
				id: "dsh-ppt",
				order: 20,
				locale: NS,
				inject: injectHero
			}, OfficePptStandardComposerDock));
		}
		//#endregion
		exports.OfficePptHeroStore = OfficePptHeroStore;
		exports.OfficePptStandardComposerDock = OfficePptStandardComposerDock;
		exports.OfficePptStandardInputAccessory = OfficePptStandardInputAccessory;
		exports.OfficePptStandardModeAction = OfficePptStandardModeAction;
		exports.apply = applyStandard;
		exports.inject = standardInject;
		return module.exports;
	}
});

//# sourceMappingURL=client.js.map
