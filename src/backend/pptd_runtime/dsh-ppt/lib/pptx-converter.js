import { markNativeShape, nativeShapeIssue } from "./imported-shape-export.js";
import path from "node:path";
import { boundedPptxGeometry, GEOMETRY_BUDGET_NAMESPACE } from "./pptx-geometry-budget.js";
import { createHash } from "node:crypto";
import yaml from "js-yaml";
import { RECOMMENDED_ZIP_LIMITS, buildPresentation, materializeSlideNodes, parseZip, serializePresentation } from "@aiden0z/pptx-renderer";
import { JSDOM } from "jsdom";
import { containsLiteralLineBreak } from "./text-escapes.js";
import { supplementResources, sanitizeOoXml, sanitizePptxFiles, serializeOoXmlElement } from "./pptx-resources.js";
import { flattenPptxGroups } from "./pptx-groups.js";
import { pptxObjectInventory, resolvePptxAlternatives } from "./pptx-object-coverage.js";
import { imageCropIssue } from "./image-crop.js";
import { resolvePptxShapeStyle, resolvePptxBackgroundStyle } from "./pptx-shape-style.js";
import { composePptxLayers } from "./pptx-layers.js";
import { convertedGeometry } from "./pptx-geometry.js";
import { boundedPptxMedia, createPptxImageReader, mediaPlaceholder } from "./pptx-media.js";
import { resolveFontFace } from "./font-family.js";
import { resolveImportedFontStyle } from "./imported-font-style.js";
import { markSourceLayout } from "./source-layout.js";
import { readPptxImageContracts, remapImageContract } from "./template-image-contract.js";
//#region lib/types/pptd-convert.js
/** Bounded PPTX to PPTD v2 conversion used by the local CLI. */
const CSS_PIXEL_TO_POINT = 72 / 96;
function record(value) {
	return typeof value === "object" && value !== null && !Array.isArray(value) ? value : void 0;
}
const PRESET_COLORS = {
	black: "000000",
	white: "FFFFFF",
	red: "FF0000",
	green: "008000",
	blue: "0000FF",
	yellow: "FFFF00",
	gray: "808080",
	grey: "808080",
	orange: "FFA500",
	purple: "800080"
};
function childElement(element, localName) {
	return element === void 0 ? void 0 : [...element.children].find((child) => child.localName === localName);
}
function descendantElement(element, localName) {
	return element === void 0 ? void 0 : [...element.getElementsByTagNameNS("*", localName)][0];
}
function safeElement(value) {
	return value?.element ?? void 0;
}
function themeForSlide(presentation, slideIndex) {
	const layout = presentation.slideToLayout.get(slideIndex);
	const master = layout === void 0 ? void 0 : presentation.layoutToMaster.get(layout);
	const theme = master === void 0 ? void 0 : presentation.masterToTheme.get(master);
	return theme === void 0 ? void 0 : presentation.themes.get(theme);
}
function resolvedTypeface(value, theme) {
	if (value === void 0 || value === "") return void 0;
	if (value.startsWith("+mj")) return theme?.majorFont.ea || theme?.majorFont.latin || "MiSans";
	if (value.startsWith("+mn")) return theme?.minorFont.ea || theme?.minorFont.latin || "MiSans";
	return value;
}
function applyLuminance(hex, colorNode) {
	const luminanceModifier = Number(descendantElement(colorNode, "lumMod")?.getAttribute("val") ?? 1e5) / 1e5;
	const luminanceOffset = Number(descendantElement(colorNode, "lumOff")?.getAttribute("val") ?? 0) / 1e5;
	return [
		0,
		2,
		4
	].map((index) => Number.parseInt(hex.slice(index, index + 2), 16)).map((value) => Math.max(0, Math.min(255, Math.round(value * luminanceModifier + 255 * luminanceOffset))).toString(16).padStart(2, "0")).join("").toUpperCase();
}
function ooxmlColor(element, theme) {
	if (element === void 0) return void 0;
	const colorNode = [
		"srgbClr",
		"schemeClr",
		"sysClr",
		"prstClr"
	].map((name) => descendantElement(element, name)).find((value) => value !== void 0);
	if (colorNode === void 0) return void 0;
	const name = colorNode.localName;
	const raw = colorNode.getAttribute("val") ?? "";
	const base = name === "srgbClr" ? raw : name === "schemeClr" ? theme?.colorScheme.get({
		tx1: "dk1",
		tx2: "dk2",
		bg1: "lt1",
		bg2: "lt2"
	}[raw] ?? raw) : name === "sysClr" ? colorNode.getAttribute("lastClr") ?? raw : PRESET_COLORS[raw.toLowerCase()];
	if (base === void 0 || !/^[0-9a-f]{6}$/iu.test(base)) return void 0;
	const alpha = Number(descendantElement(colorNode, "alpha")?.getAttribute("val") ?? 1e5) / 1e5;
	const opacity = Math.max(0, Math.min(255, Math.round(alpha * 255))).toString(16).padStart(2, "0").toUpperCase();
	return `#${applyLuminance(base.toUpperCase(), colorNode)}${opacity === "FF" ? "" : opacity}`;
}
function convertedFill(value, theme) {
	const fill = safeElement(value);
	if (fill === void 0 || fill.localName === "noFill") return void 0;
	if (fill.localName === "solidFill") {
		const resolved = ooxmlColor(fill, theme);
		return resolved === void 0 ? void 0 : {
			type: "solid",
			color: resolved
		};
	}
	if (fill.localName === "gradFill") {
		const stops = [...fill.getElementsByTagNameNS("*", "gs")].map((stop) => ({
			position: Number(stop.getAttribute("pos") ?? 0) / 1e5,
			color: ooxmlColor(stop, theme)
		})).filter((stop) => stop.color !== void 0);
		if (stops.length < 2) return void 0;
		const pathNode = childElement(fill, "path");
		const angle = Number(childElement(fill, "lin")?.getAttribute("ang") ?? 0) / 6e4;
		return {
			type: "gradient",
			gradientType: pathNode === void 0 ? "linear" : "radial",
			angle,
			stops
		};
	}
}
function convertedBorder(value, theme) {
	const line = safeElement(value);
	if (line === void 0 || childElement(line, "noFill") !== void 0) return void 0;
	const color = ooxmlColor(line, theme);
	if (color === void 0 || (color.length === 9 && color.endsWith("00"))) return void 0;
	const dashValue = childElement(line, "prstDash")?.getAttribute("val") ?? "solid";
	return {
		style: dashValue.includes("dot") ? "dot" : dashValue === "solid" ? "solid" : "dash",
		width: Math.max(.1, Number(line.getAttribute("w") ?? 12700) / 12700),
		color
	};
}
function points(value) {
	return Number((value * CSS_PIXEL_TO_POINT).toFixed(3));
}
function safeId(value, fallback) {
	return (value.normalize("NFKC").replace(/[^A-Za-z0-9._-]+/gu, "-").replace(/^-+|-+$/gu, "") || fallback).slice(0, 96);
}
function htmlEscape(value) {
	return value.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll("\"", "&quot;");
}
function bounds(node, offsetX = 0, offsetY = 0) {
	return [
		points(node.position.x + offsetX),
		points(node.position.y + offsetY),
		points(node.size.w),
		points(node.size.h)
	];
}
function textRunStyle(properties, theme, text = "") {
	const color = ooxmlColor(childElement(properties, "solidFill"), theme);
	const latin = descendantElement(properties, "latin")?.getAttribute("typeface") ?? void 0;
	const eastAsian = descendantElement(properties, "ea")?.getAttribute("typeface") ?? void 0;
	const isCjk=/[\u2e80-\u9fff\uac00-\ud7af]/u.test(text);
  const eaFace=resolvedTypeface(eastAsian,theme), latinFace=resolvedTypeface(latin,theme);
  // A generic Latin-only EA default yields to an authored CJK Latin face.
  const fontFamily = isCjk && eaFace && resolveFontFace(eaFace,'Arial',text)!==eaFace && latinFace
    ? resolveFontFace(latinFace,'Arial',text)
    : resolvedTypeface(isCjk ? eastAsian || latin : latin || eastAsian, theme);
	const fontSizeRaw = Number(properties?.getAttribute("sz"));
	return {
		...Number.isFinite(fontSizeRaw) && fontSizeRaw > 0 ? { fontSize: fontSizeRaw / 100 } : {},
        ...resolveImportedFontStyle(fontFamily),
		...color === void 0 ? {} : { color },
        ...(childElement(properties,"highlight") ? {highlight:ooxmlColor(childElement(properties,"highlight"),theme)} : {}),
        ...(properties?.getAttribute("u") && properties.getAttribute("u")!=="none" ? {underline:true} : {}),
		...(properties?.hasAttribute("spc") ? { letterSpacing: Number(properties.getAttribute("spc")) / 100 } : {}),
        ...(properties?.hasAttribute("baseline") ? { baseline: Number(properties.getAttribute("baseline")) / 100000 * (fontSizeRaw / 100 || 18) } : {}),
		...properties?.getAttribute("b") === "1" ? { bold: true } : {},
		...properties?.getAttribute("i") === "1" ? { italic: true } : {}
	};
}
function runMarkup(text, style) {
	const declarations = [];
	if (typeof style.color === "string") declarations.push(`color:${style.color}`);
	if (typeof style.fontSize === "number") declarations.push(`font-size:${style.fontSize}px`);
	if (typeof style.fontFamily === "string") declarations.push(`font-family:${style.fontFamily}`);
	if (typeof style.letterSpacing === "number") declarations.push(`letter-spacing:${style.letterSpacing}px`);
	if (style.bold === true) declarations.push("font-weight:700");
	if (style.italic === true) declarations.push("font-style:italic");
	const escaped = htmlEscape(text).replaceAll("\n", "<br/>");
	return declarations.length === 0 ? escaped : `<span style="${declarations.join(";")}">${escaped}</span>`;
}
/** Resolve OOXML placeholder/list defaults before converting individual runs. */
function isTextBox(source) {
  return ['1','true'].includes(childElement(childElement(source,'nvSpPr'),'cNvSpPr')?.getAttribute('txBox'));
}
function inheritedTextBody(presentation, slideIndex, shape) {
  const textBody = shape.textBody;
  if (!textBody) return textBody;
  const layoutId = presentation.slideToLayout.get(slideIndex);
  const layout = presentation.layouts.get(layoutId);
  const master = presentation.masters.get(presentation.layoutToMaster.get(layoutId));
  const source = safeElement(shape.source);
  const ph = descendantElement(source, 'ph');
  const type = ph?.getAttribute('type') ?? 'obj';
  const index = ph?.getAttribute('idx') ?? '0';
  function placeholder(tree) {
    if (!ph) return undefined;
    return [...(safeElement(tree)?.children ?? [])].find(node => {
      const candidate = descendantElement(node, 'ph');
      return candidate && (candidate.getAttribute('idx') ?? '0') === index &&
        ((candidate.getAttribute('type') ?? 'obj') === type || index !== '0');
    });
  }
  const masterShape = placeholder(master?.spTree);
  const layoutShape = placeholder(layout?.spTree);
  const bodies = [childElement(masterShape, 'txBody'), childElement(layoutShape, 'txBody'), childElement(source, 'txBody')];
  function merge(elements, name) {
    const target = source.ownerDocument.createElementNS('http://schemas.openxmlformats.org/drawingml/2006/main', `a:${name}`);
    for (const element of elements.filter(Boolean)) {
      for (const attr of element.attributes) target.setAttribute(attr.name, attr.value);
      for (const child of element.children) {
        const fill = ['solidFill', 'noFill', 'gradFill'].includes(child.localName);
        const fit = ['noAutofit','normAutofit','spAutoFit'].includes(child.localName);
        for (const old of [...target.children]) if (old.localName === child.localName || (fill && ['solidFill', 'noFill', 'gradFill'].includes(old.localName)) || (fit && ['noAutofit','normAutofit','spAutoFit'].includes(old.localName))) target.removeChild(old);
        target.appendChild(child.cloneNode(true));
      }
    }
    return target;
  }
  // Free textboxes use presentation defaults and their own list/paragraph styles.
  // Placeholder styles belong to the matched master/layout; otherStyle serves shape text.
  const masterStyle = ph || !isTextBox(source)
    ? master?.textStyles?.[type === 'title' || type === 'ctrTitle' ? 'titleStyle' : type === 'body' ? 'bodyStyle' : 'otherStyle']
    : undefined;
  const paragraphs = textBody.paragraphs.map(paragraph => {
    const levelName = `lvl${(paragraph.level ?? 0) + 1}pPr`;
    const defaults = [safeElement(presentation.defaultTextStyle), safeElement(master?.defaultTextStyle), safeElement(masterStyle)]
      .flatMap(style => [childElement(style, 'defPPr'),childElement(style, levelName)]);
    for (const body of bodies) { const style=childElement(body, 'lstStyle');defaults.push(childElement(style,'defPPr'),childElement(style,levelName)); }
    const paragraphProperties = merge([...defaults, safeElement(paragraph.properties)], 'pPr');
    const runDefaults = [...defaults, safeElement(paragraph.properties)].map(properties => childElement(properties, 'defRPr'));
    return { ...paragraph, properties: { element: paragraphProperties }, runs: paragraph.runs.map(run => ({ ...run,
      properties: { element: merge([...runDefaults, safeElement(run.properties)], 'rPr') }
    })) };
  });
  return { ...textBody, paragraphs, bodyProperties: { element: merge(bodies.map(body => childElement(body, 'bodyPr')), 'bodyPr') } };
}
function preservedTextBody(textBody, theme) {
  const doc=safeElement(textBody.bodyProperties)?.ownerDocument;
  if(!doc)return undefined;
  const A='http://schemas.openxmlformats.org/drawingml/2006/main';
  const body=doc.createElementNS('http://schemas.openxmlformats.org/presentationml/2006/main','p:txBody');
  const bodyProperties=safeElement(textBody.bodyProperties).cloneNode(true);
  // Imported templates retain their authored frames. Grow-to-fit is normalized
  // to native shrink-to-fit so different font metrics stay within those frames.
  const grow=childElement(bodyProperties,'spAutoFit');
  if(grow)grow.replaceWith(doc.createElementNS(A,'a:normAutofit'));
  body.appendChild(bodyProperties);
  body.appendChild(doc.createElementNS(A,'a:lstStyle'));
  for(const paragraph of textBody.paragraphs){
    const p=doc.createElementNS(A,'a:p');
    if(safeElement(paragraph.properties))p.appendChild(safeElement(paragraph.properties).cloneNode(true));
    for(const run of paragraph.runs){
      const r=doc.createElementNS(A,'a:r');
      const props=safeElement(run.properties)?.cloneNode(true) ?? doc.createElementNS(A,'a:rPr');
      // Flatten font inheritance into the font actually selected for this script.
      // Source theme font slots belong to the original package, whereas this deck
      // has its own theme. Explicit slots preserve glyph selection after export.
      const style=textRunStyle(safeElement(run.properties),theme,run.text);
      const face=resolveFontFace(style.fontFamily, "Arial", run.text);
      if(style.bold)props.setAttribute('b','1');
      if(face)for(const font of ['latin','ea','cs']){
        let child=childElement(props,font);
        if(!child){child=doc.createElementNS(A,`a:${font}`);props.appendChild(child);}
        for(const attr of [...child.attributes])child.removeAttributeNode(attr);
        child.setAttribute('typeface',face);
      }
      const fill=childElement(props,'solidFill'), value=ooxmlColor(fill,theme);
      if(fill&&value){const alpha=[...fill.getElementsByTagNameNS('*','alpha')].map(n=>n.cloneNode(true));while(fill.firstChild)fill.firstChild.remove();const c=doc.createElementNS(A,'a:srgbClr');c.setAttribute('val',value.slice(1,7));alpha.forEach(n=>c.appendChild(n));fill.appendChild(c);}
      for(const link of [...props.getElementsByTagNameNS('*','hlinkClick'),...props.getElementsByTagNameNS('*','hlinkMouseOver')])link.remove();
      r.appendChild(props);const t=doc.createElementNS(A,'a:t');t.textContent=run.text;r.appendChild(t);p.appendChild(r);
    }
    if(safeElement(paragraph.endParaRPr))p.appendChild(safeElement(paragraph.endParaRPr).cloneNode(true));
    body.appendChild(p);
  }
  // DrawingML children have schema-defined order; inheritance merging must preserve it.
  const orders={pPr:['lnSpc','spcBef','spcAft','buClrTx','buClr','buSzTx','buSzPct','buSzPts','buFontTx','buFont','buNone','buAutoNum','buChar','buBlip','tabLst','defRPr','extLst'],rPr:['ln','noFill','solidFill','gradFill','blipFill','pattFill','grpFill','effectLst','effectDag','highlight','uLnTx','uLn','uFillTx','uFill','latin','ea','cs','sym','hlinkClick','hlinkMouseOver','rtl','extLst']};
  for(const node of body.getElementsByTagNameNS('*','*')){
    // Empty paragraphs and inherited run defaults also contribute font metrics.
    // Resolve their full-face names through the same contract as visible runs.
    if(['rPr','defRPr','endParaRPr'].includes(node.localName))for(const font of [...node.children]){
      if(!['latin','ea','cs','sym'].includes(font.localName))continue;
      const style=resolveImportedFontStyle(font.getAttribute('typeface'));
      if(style.fontFamily)font.setAttribute('typeface',style.fontFamily);
      if(style.bold)node.setAttribute('b','1');
    }
    const order=orders[node.localName];if(!order)continue;
    [...node.children].sort((a,b)=>order.indexOf(a.localName)-order.indexOf(b.localName)).forEach(child=>node.appendChild(child));
  }
  return serializeOoXmlElement(body);
}
function convertedText(node, textBody, theme) {
	const body = safeElement(textBody?.bodyProperties);
	const paragraphs = textBody?.paragraphs ?? [];
	const firstParagraph = paragraphs[0];
	const firstRun = paragraphs.flatMap((paragraph) => paragraph.runs).find((run) => run.text.trim() !== "");
	const base = textRunStyle(safeElement(firstRun?.properties), theme, firstRun?.text);
	const paragraphAlignment = safeElement(firstParagraph?.properties)?.getAttribute("algn");
	const horizontal = paragraphAlignment === "ctr" ? "center" : paragraphAlignment === "r" ? "right" : paragraphAlignment === "just" || paragraphAlignment === "dist" ? "justify" : "left";
	const anchor = body?.getAttribute("anchor");
	const vertical = anchor === "ctr" ? "middle" : anchor === "b" ? "bottom" : "top";
	const markup = paragraphs.length === 0 ? (node.textBody?.paragraphs ?? []).map((paragraph) => `<p>${htmlEscape(paragraph.text).replaceAll("\n", "<br/>")}</p>`).join("") : paragraphs.map((paragraph) => {
		const properties = safeElement(paragraph.properties);
		const bullet = descendantElement(properties, "buChar")?.getAttribute("char") ?? (descendantElement(properties, "buAutoNum") === void 0 ? "" : "•");
		const content = paragraph.runs.map((run) => runMarkup(run.text, textRunStyle(safeElement(run.properties), theme, run.text))).join("");
		return `<p>${bullet === "" ? "" : `${htmlEscape(bullet)} `}${content}</p>`;
	}).join("");
  const sourceParagraphs = paragraphs.map(paragraph => {
    const properties = safeElement(paragraph.properties);
    const spacing = name => {
      const item = childElement(properties, name);
      const pts = childElement(item, 'spcPts');
      const pct = childElement(item, 'spcPct');
      return pts ? {points:Number(pts.getAttribute('val'))/100} : pct ? {ratio:Number(pct.getAttribute('val'))/100000} : {};
    };
    const number = name => properties?.hasAttribute(name) ? Number(properties.getAttribute(name))/12700 : 0;
    const line = spacing('lnSpc'), before=spacing('spcBef'), after=spacing('spcAft');
    const runs = paragraph.runs.map(run => ({text:run.text,options:{
      fontSize:18,fontFamily:theme?.minorFont.ea || theme?.minorFont.latin || "MiSans",color:"#000000",
      ...textRunStyle(safeElement(run.properties),theme,run.text)}}));
    const bullet = childElement(properties,'buChar')?.getAttribute('char');
    if (bullet) runs.unshift({text:(bullet==='\uf0fc'?'✓':bullet)+' ',options:base});
    const autoNumber = childElement(properties,'buAutoNum');
    return {runs,...(autoNumber?{numbering:{type:autoNumber.getAttribute('type'),startAt:Number(autoNumber.getAttribute('startAt')??1)}}:{}),fontSize:Number(safeElement(paragraph.endParaRPr)?.getAttribute('sz') ?? 1800)/100,marginLeft:number('marL'),marginRight:number('marR'),indent:number('indent'),
      align:({ctr:'center',r:'right',just:'justify',dist:'justify'})[properties?.getAttribute('algn')] ?? 'left',
      lineHeight:line.ratio ?? 1, ...(line.points ? {lineSpacing:line.points} : {}),
      spaceBefore:before.points ?? (before.ratio ?? 0)*(base.fontSize ?? 18),
      spaceAfter:after.points ?? (after.ratio ?? 0)*(base.fontSize ?? 18),
      tabStops:[...(childElement(properties,'tabLst')?.children ?? [])].map(tab=>({position:Number(tab.getAttribute('pos'))/12700,alignment:tab.getAttribute('algn') ?? 'l'}))};
  });
  const margins = ['tIns','rIns','bIns','lIns'].map((name,i)=>Number(body?.getAttribute(name) ?? (i%2?91440:45720))/12700);
	return {
		markup,
		content: {
			fontFamily: typeof base.fontFamily === "string" ? base.fontFamily : theme?.minorFont.ea || theme?.minorFont.latin || "MiSans",
			fontSize: typeof base.fontSize === "number" ? base.fontSize : 18,
			color: typeof base.color === "string" ? base.color : "#000000",
			align: [horizontal, vertical],
			wrap: body?.getAttribute("wrap") !== "none",
			...(childElement(body, "normAutofit") || childElement(body,"spAutoFit") ? { fit: "shrink" } : {}),
			text: markup,
            ...(paragraphs.length ? {paragraphs:sourceParagraphs,nativeTextBody:preservedTextBody(textBody,theme),textBox:isTextBox(safeElement(node.source)),margins,...(childElement(body,"normAutofit")?.hasAttribute("fontScale")?{fontScale:Number(childElement(body,"normAutofit").getAttribute("fontScale"))/100000}:{}),overflow:"clip",...(childElement(body,"spAutoFit")?{sourceAutoFit:"grow"}:{})} : {}),
			...containsLiteralLineBreak(markup) ? { literalEscapes: true } : {}
		}
	};
}
function lineElement(node, elementId, offsetX, offsetY, raw, theme) {
	const width = Math.max(.001, points(node.size.w));
	const height = Math.max(.001, points(node.size.h));
	const flipHorizontal = node.flipH;
	const flipVertical = node.flipV;
	return {
		elementId,
		elementType: "line",
		bounds: bounds(node, offsetX, offsetY),
		viewBox: [width, height],
		points: `${flipHorizontal ? width : 0},${flipVertical ? height : 0} ${flipHorizontal ? 0 : width},${flipVertical ? 0 : height}`,
		border: convertedBorder(raw?.line, theme) ?? {
			style: "solid",
			width: 1,
			color: "#000000"
		},
		...node.rotation === 0 ? {} : { rotation: node.rotation }
	};
}
function preservedShapePaint(value, theme) {
    const source=safeElement(value);
    if(!source||!['solidFill','noFill','gradFill','pattFill','ln'].includes(source.localName))return undefined;
    const fill=source.cloneNode(true);
    for(const color of [...fill.getElementsByTagNameNS('*','schemeClr')]) {
        const name=color.getAttribute('val');
        const rgb=theme?.colorScheme.get({tx1:'dk1',tx2:'dk2',bg1:'lt1',bg2:'lt2'}[name]??name);
        if(!rgb||!/^[a-f0-9]{6}$/i.test(rgb))return undefined;
        const resolved=fill.ownerDocument.createElementNS(color.namespaceURI,'a:srgbClr');
        resolved.setAttribute('val',rgb.toUpperCase());
        for(const transform of color.children)resolved.appendChild(transform.cloneNode(true));
        color.replaceWith(resolved);
    }
    return serializeOoXmlElement(fill);
}
function shapeElements(node, elementId, offsetX, offsetY, raw, theme) {
	const source=safeElement(raw?.source),properties=childElement(source,'spPr');
    const paint=resolvePptxShapeStyle(source,theme);
    const geometry=childElement(properties,'prstGeom') ?? childElement(properties,'custGeom');
    const preservedFill=preservedShapePaint(paint.fill,theme),preservedLine=preservedShapePaint(paint.line,theme);
    const nativeShape=geometry ? {geometry:serializeOoXmlElement(geometry),...(preservedFill?{fill:preservedFill}:{}),...(preservedLine?{line:preservedLine}:{}),lineEnds:[...(safeElement(paint.line)?.children ?? [])].filter(node=>['headEnd','tailEnd'].includes(node.localName)).map(serializeOoXmlElement)} : undefined;
    let modelGeometry;
    if(raw?.customGeometry) {try {modelGeometry=convertedGeometry(safeElement(raw.customGeometry),points(node.size.w),points(node.size.h));}catch(error){if(!nativeShape)throw error;}}
    if(!nativeShape && (node.presetGeometry === "line" || node.presetGeometry === "straightConnector1"))return [lineElement(node,elementId,offsetX,offsetY,raw,theme)];
	const fill = convertedFill(paint.fill, theme);
	const border = convertedBorder(paint.line, theme);
	const text = convertedText({ ...node, source: raw?.source }, raw?.textBody, theme);
	const hasText = text.markup.replace(/<[^>]*>/gu, "").trim() !== "";
	const items = [];
	if (fill !== void 0 || border !== void 0 || !hasText || (preservedFill && safeElement(paint.fill).localName !== 'noFill')) items.push({
		elementId: hasText ? `${elementId}-shape` : elementId,
		elementType: "shape",
		bounds: bounds(node, offsetX, offsetY),
		...(modelGeometry ?? { shapeName: node.presetGeometry ?? (geometry?.localName==='custGeom'?'custom':'rect') }),
        ...(nativeShape ? {nativeShape} : {}),
		...fill === void 0 ? {} : { fill },
		...border === void 0 ? {} : { border },
		...node.rotation === 0 ? {} : { rotation: node.rotation },
		...!node.flipH && !node.flipV ? {} : { flip: [node.flipH, node.flipV] }
	});
	if (hasText) items.push({
		elementId: items.length === 0 ? elementId : `${elementId}-text`,
		elementType: "text",
		bounds: bounds(node, offsetX, offsetY),
		...node.rotation === 0 ? {} : { rotation: node.rotation },
		...!node.flipH && !node.flipV ? {} : { flip: [node.flipH, node.flipV] },
		content: text.content
	});
	return items;
}
function normalizedRelationshipTarget(slidePath, target) {
	if (target.startsWith("/")) return target.slice(1);
	return path.posix.normalize(path.posix.join(path.posix.dirname(slidePath), target));
}
function chartValues(root, containerName) {
	const container = root.getElementsByTagNameNS('*', containerName.split(':').at(-1))[0];
	if (container === void 0) return [];
	const multiCache = descendantElement(container, 'multiLvlStrCache');
	if (multiCache && [...multiCache.children].filter(node => node.localName === 'lvl').length > 1) throw new Error('多层图表分类使用原边界占位。');
	const cache = multiCache ? childElement(multiCache, 'lvl') : ['numCache', 'strCache', 'numLit', 'strLit'].map(name => descendantElement(container, name)).find(Boolean);
	if (!cache) return childElement(container, 'v') ? [childElement(container, 'v').textContent ?? ''] : [];
	const points = [...cache.children].filter(node => node.localName === 'pt');
	const indices = points.map(node => Number(node.getAttribute('idx')));
	const count = Number(childElement(multiCache ?? cache, 'ptCount')?.getAttribute('val') ?? 0);
	const length = Math.max(count, ...indices.map(index => index + 1), 0);
	if (!Number.isInteger(length) || length > 100000 || indices.some(index => !Number.isInteger(index) || index < 0) || new Set(indices).size !== indices.length) throw new Error('图表缓存索引应为有界、独立的数据点。');
	const values = Array(length).fill(null);
	points.forEach((point, i) => { values[indices[i]] = childElement(point, 'v')?.textContent ?? null; });
	return values;
}
function chartSeriesType(element) {
	let current = element.parentElement;
	while (current !== null) {
		const name = current.localName;
		if (name.endsWith("Chart")) {
			if (name === "barChart") return "bar";
			if (name === "lineChart") return "line";
			if (name === "areaChart") return "area";
			if (name === "pieChart" || name === "doughnutChart") return "pie";
			if (name === "radarChart") return "radar";
			if (name === "scatterChart") return "scatter";
			if (name === "bubbleChart") return "bubble";
		}
		current = current.parentElement;
	}
}
function chartContainer(element) {
	let current = element.parentElement;
	while (current !== null) {
		if (current.localName.endsWith("Chart")) return current;
		current = current.parentElement;
	}
}
function convertedChart(node, xml, elementId, offsetX, offsetY, theme) {
	const document = new DOMParser().parseFromString(sanitizeOoXml(xml), "application/xml");
	if (document.querySelector("parsererror") !== null) return void 0;
	const seriesNodes = [...document.getElementsByTagNameNS('*', 'ser')];
	if (seriesNodes.length === 0) return void 0;
	const valueAxes = [...document.getElementsByTagName("c:valAx")];
	const categoryAxis = [...document.getElementsByTagName("c:catAx")][0];
	const categoryAxisReversed = descendantElement(categoryAxis, "orientation")?.getAttribute("val") === "maxMin";
	const valueAxisIds = valueAxes.map((axis) => childElement(axis, "axId")?.getAttribute("val") ?? "");
	const axisConfig = (axis) => {
		const scaling = childElement(axis, "scaling");
		const minimum = Number(childElement(scaling, "min")?.getAttribute("val") ?? NaN);
		const maximum = Number(childElement(scaling, "max")?.getAttribute("val") ?? NaN);
		const title = descendantElement(childElement(axis, "title"), "t")?.textContent?.trim();
        const text = childElement(axis, 'txPr');
        const props = descendantElement(text, 'defRPr');
        const labelColor = ooxmlColor(props, theme);
        const labelSize = Number(props?.getAttribute('sz') ?? NaN) / 100;
        const fontFamily = descendantElement(props, 'latin')?.getAttribute('typeface');
        const position = childElement(axis, 'tickLblPos')?.getAttribute('val');
        const line = childElement(childElement(axis, 'spPr'), 'ln');
        const lineColor = ooxmlColor(line, theme);
        const grid = childElement(axis, 'majorGridlines');
        return {
			...Number.isFinite(minimum) ? { min: minimum } : {},
			...Number.isFinite(maximum) ? { max: maximum } : {},
            ...childElement(axis, 'majorUnit') ? { majorUnit: Number(childElement(axis, 'majorUnit').getAttribute('val')) } : {},
			...title === void 0 || title === "" ? {} : { title },
            hidden: childElement(axis, 'delete')?.getAttribute('val') === '1',
            ...childElement(axis, 'majorTickMark') ? { majorTick: childElement(axis, 'majorTickMark').getAttribute('val') } : {},
            ...childElement(axis, 'minorTickMark') ? { minorTick: childElement(axis, 'minorTickMark').getAttribute('val') } : {},
            label: {
                ...position ? { position } : {},
                ...Number.isFinite(labelSize) ? { fontSize: labelSize } : {},
                ...fontFamily ? { fontFamily } : {},
                ...labelColor ? { color: labelColor } : {}
            },
            ...line ? { line: childElement(line, 'noFill') ? false : {
                ...lineColor ? { color: lineColor } : {},
                ...line.hasAttribute('w') ? { width: Number(line.getAttribute('w')) / 12700 } : {}
            }} : {},
            gridLine: grid ? { color: ooxmlColor(grid, theme) ?? '#D4D4D4' } : false
        };
	};
	const plotArea = descendantElement(document.documentElement, 'plotArea');
    const manual = childElement(childElement(plotArea, 'layout'), 'manualLayout');
    const plotLayout = manual && childElement(manual, 'layoutTarget')?.getAttribute('val') === 'inner'
        && ['xMode', 'yMode'].every(key => !childElement(manual, key) || childElement(manual, key).getAttribute('val') === 'edge')
        ? Object.fromEntries(['x', 'y', 'w', 'h'].map(key => [key, Number(childElement(manual, key)?.getAttribute('val') ?? (key === 'w' || key === 'h' ? 1 : 0))])) : undefined;
    const chartLine = childElement(childElement(document.documentElement, 'spPr'), 'ln');
    const chartBorder = convertedBorder(chartLine, theme);
    const plotLine = childElement(childElement(plotArea, 'spPr'), 'ln');
    const plotBorder = convertedBorder(plotLine, theme);
    const convertedAxes = valueAxes.map(axisConfig);
    const convertedCategoryAxis = categoryAxis ? axisConfig(categoryAxis) : undefined;
	const outputSeries = [];
	const valuesBySeries = [];
	let categories = [];
	for (const [index, seriesNode] of seriesNodes.entries()) {
		const type = chartSeriesType(seriesNode);
		if (type === void 0) return void 0;
		if (type === 'bubble') return void 0;
		const container = chartContainer(seriesNode);
		const horizontal = type === "bar" && childElement(container, "barDir")?.getAttribute("val") === "bar";
		const sourceCategoryValues = type === "scatter" || type === "bubble" ? chartValues(seriesNode, "c:xVal") : chartValues(seriesNode, "c:cat");
		const categoryValues = horizontal && !categoryAxisReversed ? [...sourceCategoryValues].reverse() : sourceCategoryValues;
		if (type === 'scatter' && categories.length && JSON.stringify(categories) !== JSON.stringify(categoryValues)) return void 0;
		if (categoryValues.length > categories.length) categories = categoryValues;
		const sourceValues = type === "scatter" || type === "bubble" ? chartValues(seriesNode, "c:yVal") : chartValues(seriesNode, "c:val");
		const values = horizontal && !categoryAxisReversed ? [...sourceValues].reverse() : sourceValues;
		valuesBySeries.push(values);
		const name = chartValues(seriesNode, "c:tx")[0] ?? `Series ${index + 1}`;
		const valueColumn = `series_${index + 1}`;
		const seriesColor = ooxmlColor(childElement(seriesNode, "spPr") ?? seriesNode, theme);
		const pointColors = [...seriesNode.getElementsByTagName("c:dPt")].map((point) => ({
			index: Number(childElement(point, "idx")?.getAttribute("val") ?? 0),
			color: ooxmlColor(point, theme)
		})).filter((point) => point.color !== void 0).sort((left, right) => left.index - right.index).map((point) => point.color);
		const dataLabels = descendantElement(container, "dLbls");
		const showValue = descendantElement(dataLabels, "showVal")?.getAttribute("val") === "1";
		const showPercent = descendantElement(dataLabels, "showPercent")?.getAttribute("val") === "1";
        const labelProps = descendantElement(childElement(dataLabels, 'txPr'), 'defRPr');
        const labelSize = Number(labelProps?.getAttribute('sz') ?? NaN) / 100;
        const labelColor = ooxmlColor(labelProps, theme);
		const grouping = childElement(container, "grouping")?.getAttribute("val");
		const containerAxisIds = container === void 0 ? [] : [...container.children].filter((child) => child.localName === "axId").map((child) => child.getAttribute("val") ?? "");
		const valueAxisIndex = valueAxisIds.findIndex((axisId) => containerAxisIds.includes(axisId));
		outputSeries.push({
			type,
			encode: type === "pie" ? {
				category: "category",
				value: valueColumn
			} : type === "radar" ? {
				category: "category",
				y: valueColumn
			} : horizontal ? {
				x: valueColumn,
				y: "category"
			} : {
				x: "category",
				y: valueColumn
			},
			name,
			...pointColors.length > 0 && type === "pie" ? { fill: pointColors } : seriesColor === void 0 ? {} : type === "line" || type === "area" || type === "radar" ? { lineColor: seriesColor } : { fill: seriesColor },
			...showValue || showPercent ? { dataLabels: {
				show: true,
                ...Number.isFinite(labelSize) ? { fontSize: labelSize } : {},
                ...labelColor ? { color: labelColor } : {},
				...showPercent ? { content: "percentage" } : {}
			} } : {},
			...valueAxisIndex > 0 && !horizontal ? { yAxisIndex: valueAxisIndex } : {},
			...grouping === "stacked" ? { stack: "value" } : grouping === "percentStacked" ? { stack: "percent" } : {},
			...type === "pie" && seriesNode.parentElement?.localName === "doughnutChart" ? { innerRadius: .5 } : {}
		});
	}
	const length = Math.max(categories.length, ...valuesBySeries.map((values) => values.length));
	const rows = Array.from({ length }, (_value, row) => [categories[row] ?? String(row + 1), ...valuesBySeries.map((values) => values[row] == null || values[row] === "" ? null : Number(values[row]))]);
	if (!length || rows.some(row => row.slice(1).some(value => value !== null && !Number.isFinite(value)))) return void 0;
	return {
		elementId,
		elementType: "chart",
		bounds: bounds(node, offsetX, offsetY),
		data: {
			cols: ["category", ...valuesBySeries.map((_values, index) => `series_${index + 1}`)],
			rows
		},
		series: outputSeries,
        ...plotLayout && Object.values(plotLayout).every(Number.isFinite) ? { plotLayout } : {},
        ...chartBorder ? { border: chartBorder } : {},
        ...plotBorder ? { plotBorder } : {},
		legend: outputSeries.length > 1,
		fontFamily: convertedCategoryAxis?.label.fontFamily ?? convertedAxes[0]?.label.fontFamily ?? "MiSans",
        ...convertedCategoryAxis ? outputSeries.some(item => record(item.encode)?.y === "category") ? { yAxis: convertedCategoryAxis } : { xAxis: convertedCategoryAxis } : {},
		...outputSeries.some((item) => record(item.encode)?.y === "category") ? convertedAxes[0] === void 0 || Object.keys(convertedAxes[0]).length === 0 ? {} : { xAxis: convertedAxes[0] } : convertedAxes.length === 0 ? {} : { yAxis: convertedAxes.length === 1 ? convertedAxes[0] : convertedAxes }
	};
}
function convertedTable(node, elementId, offsetX, offsetY, raw, theme) {
	const columns = node.columns ?? [];
	const rows = node.rows ?? [];
	const totalWidth = columns.reduce((sum, value) => sum + value, 0) || 1;
	const totalHeight = rows.reduce((sum, row) => sum + row.height, 0) || 1;
	return {
		elementId,
		elementType: "table",
		bounds: bounds(node, offsetX, offsetY),
		columnWidths: columns.map((value) => Number((value / totalWidth).toFixed(6))),
		rowHeights: rows.map((row) => Number((row.height / totalHeight).toFixed(6))),
		rows: rows.map((row, rowIndex) => row.cells.map((cell, columnIndex) => {
			const rawCell = raw?.rows[rowIndex]?.cells[columnIndex];
			const properties = safeElement(rawCell?.properties);
			const fillElement = [
				"solidFill",
				"gradFill",
				"noFill"
			].map((name) => childElement(properties, name)).find((value) => value !== void 0);
			const lineElement = [
				"ln",
				"lnL",
				"lnR",
				"lnT",
				"lnB"
			].map((name) => childElement(properties, name)).find((value) => value !== void 0);
			const text = convertedText({
				...node,
				textBody: {
					paragraphs: [{
						level: 0,
						text: cell.text
					}],
					totalText: cell.text
				}
			}, rawCell?.textBody, theme);
			const align = Array.isArray(text.content.align) ? text.content.align : void 0;
			return {
				text: cell.text,
				...containsLiteralLineBreak(cell.text) ? { literalEscapes: true } : {},
				...cell.gridSpan > 1 ? { colSpan: cell.gridSpan } : {},
				...cell.rowSpan > 1 ? { rowSpan: cell.rowSpan } : {},
				...fillElement === void 0 ? {} : { fill: convertedFill({ element: fillElement }, theme) },
				...lineElement === void 0 ? {} : { border: convertedBorder({ element: lineElement }, theme) },
				...typeof text.content.fontFamily === "string" ? { fontFamily: text.content.fontFamily } : {},
				...typeof text.content.fontSize === "number" ? { fontSize: text.content.fontSize } : {},
				...typeof text.content.color === "string" ? { color: text.content.color } : {},
				...text.content.bold === true ? { bold: true } : {},
				...text.content.italic === true ? { italic: true } : {},
				...align === void 0 ? {} : { align }
			};
		}))
	};
}
function yamlText(value) {
	return yaml.dump(value, {
		schema: yaml.JSON_SCHEMA,
		noRefs: true,
		lineWidth: -1,
		sortKeys: false
	});
}
function installDomParser() {
	const previous = globalThis.DOMParser;
	const window = new JSDOM("").window;
	Object.defineProperty(globalThis, "DOMParser", {
		configurable: true,
		writable: true,
		value: window.DOMParser
	});
	return () => {
		window.close();
		if (previous === void 0) Reflect.deleteProperty(globalThis, "DOMParser");
		else Object.defineProperty(globalThis, "DOMParser", {
			configurable: true,
			writable: true,
			value: previous
		});
	};
}
/** Convert one bounded PPTX package into an editable, self-contained PPTD v2 project. */
let pptxConversionTail = Promise.resolve();
function convertPptxToPptd(bytes, fileName, {signal} = {}) {
	const pending = pptxConversionTail.catch(() => {}).then(() => convertPptxWithDomParser(bytes, fileName, signal));
	pptxConversionTail = pending;
	return pending;
}
async function convertPptxWithDomParser(bytes, fileName, signal) {
	signal?.throwIfAborted();
	const restoreDomParser = installDomParser();
	try {
		const bounded = boundedPptxMedia(bytes);
		const input = bounded.bytes;
		const files = sanitizePptxFiles(supplementResources(await parseZip(input.buffer.slice(input.byteOffset, input.byteOffset + input.byteLength), RECOMMENDED_ZIP_LIMITS), input));
		const diagnostics = [];
		const imageContracts = readPptxImageContracts(input);
		const readImage = createPptxImageReader();
        for(const group of [files.slides,files.slideLayouts,files.slideMasters])
            for(const [part,xml] of group)group.set(part,boundedPptxGeometry(xml));
        await composePptxLayers(files);
        const groupFallbacks = new Map();
        for (const [slidePath, xml] of files.slides) {
            await new Promise(resolve=>setImmediate(resolve));
            signal?.throwIfAborted();
            const alternatives = resolvePptxAlternatives(xml);
            await new Promise(resolve=>setImmediate(resolve));
            signal?.throwIfAborted();
            const flattened = flattenPptxGroups(alternatives.xml);
            files.slides.set(slidePath, flattened.xml);
            groupFallbacks.set(slidePath, new Map((flattened.fallbacks ?? []).map(item => [item.nodeId, item])));
            if (flattened.count) diagnostics.push({ level: "normalized", feature: "group", message: `${flattened.count} 个组合已展开为页面对象，变换降级详情按对象记录。` });
            if (alternatives.count) diagnostics.push({ level: "normalized", feature: "alternate-content", message: `${alternatives.count} 个兼容分支已按源文件的备用表示导入。` });
        }
        // Keep one page's XML tree alive. Dense vectors can expand a small XML
        // package into several gigabytes when every page retains its DOM nodes.
        const presentation = buildPresentation(files, {lazySlides:true});
		const pages = /* @__PURE__ */ new Map();
		const assets = /* @__PURE__ */ new Map();
		let sourceNodeCount = 0;
		let outputElementCount = 0;
        let title;
        const convertSlide = async sourceSlide => {
            materializeSlideNodes(presentation,sourceSlide);
            for(const node of sourceSlide.nodes) if(node.nodeType==='shape' && node.textBody) node.textBody=inheritedTextBody(presentation,sourceSlide.index,node);
            const serialized=serializePresentation({...presentation,slides:[sourceSlide]});
            const slide={...serialized.slides[0],index:sourceSlide.index};
            if(slide.index===0) title=slide.nodes.find(node=>node.textBody?.totalText.trim()!=='')?.textBody?.totalText.trim()?.split(/\r?\n/u)[0]?.slice(0,160);
			const theme = themeForSlide(presentation, slide.index);
			const output = [];
			const elementNames = new Map();
			const putAsset = (image) => {
				const digest = createHash('sha256').update(image.bytes).digest('hex');
				const extension = image.type === 'image/jpeg' ? '.jpg' : image.type === 'image/svg+xml' ? '.svg' : `.${image.type.slice(6)}`;
				const assetPath = `media/${digest.slice(0, 24)}${extension}`;
				assets.set(assetPath, { path: assetPath, mediaType: image.type, bytes: image.bytes, sha256: digest });
				return assetPath;
			};
			const putPlaceholder = async (node, elementId, offsetX, offsetY, feature, message) => {
				const frame = bounds(node, offsetX, offsetY);
				if (frame.some(value => !Number.isFinite(value)) || frame[2] <= 0 || frame[3] <= 0) {
					diagnostics.push({ level: 'unsupported', slide: slide.index + 1, nodeId: node.id, elementId, feature, message: '该对象需要有效的二维边界以保留原位置。' });
					return;
				}
				const src = putAsset(await mediaPlaceholder(frame, feature));
				output.push({ elementId, elementType: 'image', bounds: frame, src, fit: { mode: 'fill' },
					...node.rotation ? { rotation: node.rotation } : {}, ...node.flipH || node.flipV ? { flip: [!!node.flipH, !!node.flipV] } : {} });
				outputElementCount++;
				diagnostics.push({ level: 'placeholder', slide: slide.index + 1, nodeId: node.id, elementId, feature, message, bounds: frame });
			};
			const convertNode = async (node, offsetX = 0, offsetY = 0, rawNode) => {
				sourceNodeCount += 1;
				// Display names can repeat or collapse after normalization; source traversal owns identity.
				const elementId = `slide-${slide.index + 1}-node-${sourceNodeCount}-${safeId(node.name, node.nodeType)}`;
				if (node.name) elementNames.set(node.name, [...(elementNames.get(node.name) ?? []), elementId]);
				const fallback = groupFallbacks.get(sourceSlide.slidePath)?.get(node.id);
				if (fallback) { await putPlaceholder(node, elementId, offsetX, offsetY, fallback.feature, fallback.message); return; }
				if (node.nodeType === "group") {
					diagnostics.push({
						level: "normalized",
						slide: slide.index + 1,
						nodeId: node.id,
						feature: "group",
						message: "组合对象已展开为顺序 PPTD 元素。"
					});
					for (const child of node.children ?? []) await convertNode(child, offsetX + node.position.x, offsetY + node.position.y);
					return;
				}
				if (node.nodeType === "shape") {
					const rawShape = rawNode?.nodeType === "shape" ? rawNode : void 0;
					let elements;
                    try {
                      if(descendantElement(safeElement(rawShape?.source),'prstGeom')?.getAttributeNS(GEOMETRY_BUDGET_NAMESPACE,'placeholder'))throw new Error('图形路径超过解析预算，已保留原位置占位。');
                      elements = shapeElements(node, elementId, offsetX, offsetY, rawShape, theme);
                      for (const element of elements) { const issue = nativeShapeIssue(element); if (issue) throw new Error(issue); }
                    }
                    catch (error) {
                      await putPlaceholder(node, elementId, offsetX, offsetY, 'shape-geometry', error.message);
                      return;
                    }
					output.push(...elements);
					outputElementCount += elements.length;
					if (['effectLst','effectDag','scene3d','sp3d','prstTxWarp'].some(name => descendantElement(safeElement(rawShape?.source), name))) diagnostics.push({
						level: "normalized",
						slide: slide.index + 1,
						nodeId: node.id,
						feature: "shape-style",
						message: "几何和段落按源数据保留；阴影、发光和三维效果按当前图形能力简化。"
					});
					return;
				}
				if (node.nodeType === "table") {
					output.push(convertedTable(node, elementId, offsetX, offsetY, rawNode?.nodeType === "table" ? rawNode : void 0, theme));
					outputElementCount += 1;
					return;
				}
				if (node.nodeType === "chart" && node.chartPath !== void 0) {
					const chartXml = files.charts.get(node.chartPath) ?? files.charts.get(node.chartPath.replace(/^\//u, ""));
					let chart, reason = '图表类型或缓存数据使用原边界占位。';
					try { chart = chartXml === undefined ? undefined : convertedChart(node, chartXml, elementId, offsetX, offsetY, theme); }
					catch (error) { reason = error.message; }
					if (chart === void 0) await putPlaceholder(node, elementId, offsetX, offsetY, 'chart', reason);
					else {
						output.push(chart);
						outputElementCount += 1;
						diagnostics.push({
							level: "normalized",
							slide: slide.index + 1,
							nodeId: node.id,
							feature: "chart-style",
							message: "PPTX 图表数据和类型已保留，复杂 OOXML 样式进入标准 PPTD 图表主题。"
						});
					}
					return;
				}
                if (node.nodeType === "picture") {
                    const rawPicture = rawNode?.nodeType === "picture" ? rawNode : void 0;
                    const svgEmbed = descendantElement(safeElement(rawPicture?.source), "svgBlip")?.getAttributeNS("http://schemas.openxmlformats.org/officeDocument/2006/relationships", "embed");
                    const relationship = sourceSlide.rels.get(svgEmbed || node.blipEmbed);
					const mediaPath = relationship === void 0 ? void 0 : normalizedRelationshipTarget(sourceSlide.slidePath, relationship.target);
                    const playbackEmbed = descendantElement(safeElement(rawPicture?.source), 'media')?.getAttributeNS('http://schemas.openxmlformats.org/officeDocument/2006/relationships', 'embed');
                    const playbackRelation = sourceSlide.rels.get(rawPicture?.mediaRId || playbackEmbed);
                    const feature = rawPicture?.isAudio || /\.(?:mp3|wav|m4a|ogg|wma)$/i.test(playbackRelation?.target ?? '') ? 'audio'
                      : rawPicture?.isVideo || playbackEmbed ? 'video' : 'picture';
                    let image = feature !== 'picture' ? { reason: '播放资源已按原位置保留占位。' }
                      : bounded.omitted.has(mediaPath) ? { reason: bounded.omitted.get(mediaPath) }
                      : await readImage(mediaPath ?? '', mediaPath === undefined ? undefined : files.media.get(mediaPath));
                    const placeholder = !!image.reason;
                    if (!placeholder && rawPicture?.crop && imageCropIssue(rawPicture.crop)) {
                      await putPlaceholder(node, elementId, offsetX, offsetY, 'picture-crop', imageCropIssue(rawPicture.crop)); return;
                    }
                    if (placeholder) {
                      diagnostics.push({ level: 'placeholder', slide: slide.index + 1, nodeId: node.id, elementId, feature,
                        message: image.reason, bounds: bounds(node, offsetX, offsetY) });
                      image = await mediaPlaceholder(bounds(node, offsetX, offsetY), feature);
                    }
                    const { bytes: media, type } = image;
					const digest = createHash("sha256").update(media).digest("hex");
					const extension = type === "image/jpeg" ? ".jpg" : type === "image/svg+xml" ? ".svg" : `.${type.slice(6)}`;
					const assetPath = `media/${digest.slice(0, 24)}${extension}`;
					assets.set(assetPath, {
						path: assetPath,
						mediaType: type,
						bytes: media,
						sha256: digest
					});
					output.push({
						elementId,
						elementType: "image",
						bounds: bounds(node, offsetX, offsetY),
						src: assetPath,
						fit: { mode: "fill" },
						...placeholder || !rawPicture?.crop ? {} : { crop: rawPicture.crop },
						...!node.flipH && !node.flipV ? {} : { flip: [node.flipH, node.flipV] },
						...node.rotation === 0 ? {} : { rotation: node.rotation },
						...placeholder || rawPicture?.presetGeometry === void 0 || rawPicture.presetGeometry === "rect" ? {} : { cropShape: { shapeName: rawPicture.presetGeometry } },
						...placeholder || convertedBorder(rawPicture?.line, theme) === void 0 ? {} : { border: convertedBorder(rawPicture?.line, theme) }
					});
					outputElementCount += 1;
					return;
				}
				await putPlaceholder(node, elementId, offsetX, offsetY, node.feature ?? node.nodeType, '该对象使用原边界占位，原稿保留源内容。');
			};
			const inventory = pptxObjectInventory(files.slides.get(sourceSlide.slidePath));
			for (const sourceObject of inventory) {
				const node = slide.nodes.find(candidate => candidate.id === sourceObject.id);
				await convertNode(node ?? sourceObject, 0, 0, sourceSlide.nodes.find(candidate => candidate.id === sourceObject.id));
                await new Promise(resolve=>setImmediate(resolve));
                signal?.throwIfAborted();
			}
			const pagePath = `pages/page-${slide.index + 1}.page`;
			const backgroundContainer = safeElement(sourceSlide.background);
			const backgroundPaint=resolvePptxBackgroundStyle(backgroundContainer,theme);
			const backgroundFillElement=safeElement(backgroundPaint);
			const background=convertedFill(backgroundPaint,theme);
			const canvasBounds = [0, 0, points(serialized.width), points(serialized.height)];
			const imageFill = backgroundFillElement?.localName==='blipFill'?backgroundFillElement:undefined;
			const nativeFill = ['gradFill','pattFill'].includes(backgroundFillElement?.localName)?backgroundFillElement:undefined;
			if (imageFill) {
				const embed = descendantElement(imageFill, 'blip')?.getAttributeNS('http://schemas.openxmlformats.org/officeDocument/2006/relationships','embed');
				const relation = sourceSlide.rels.get(embed);
				const mediaPath = relation && normalizedRelationshipTarget(sourceSlide.slidePath, relation.target);
				let image = bounded.omitted.has(mediaPath) ? { reason: bounded.omitted.get(mediaPath) } : await readImage(mediaPath ?? '', mediaPath ? files.media.get(mediaPath) : undefined);
				const srcRect = descendantElement(imageFill,'srcRect');
				const crop = srcRect && Object.fromEntries(Object.entries({left:'l',top:'t',right:'r',bottom:'b'}).map(([key,attr])=>[key,Number(srcRect.getAttribute(attr)??0)/100000]));
				if (crop && imageCropIssue(crop)) image = { reason: imageCropIssue(crop) };
				const placeholder=!!image.reason,elementId=`slide-${slide.index+1}-background`;
				if (placeholder) {
					diagnostics.push({ level:'placeholder',slide:slide.index+1,elementId,feature:'background-picture',message:image.reason,bounds:canvasBounds });
					image=await mediaPlaceholder(canvasBounds,'picture');
				}
				output.unshift({elementId,elementType:'image',bounds:canvasBounds,src:putAsset(image),fit:{mode:'fill'},...!placeholder && crop ? {crop} : {}});
				outputElementCount++;
				if (descendantElement(imageFill,'tile')) diagnostics.push({level:'normalized',slide:slide.index+1,feature:'background-tile',message:'平铺背景按页面边界填充。'});
			} else if (nativeFill) {
				const fill=preservedShapePaint({element:nativeFill},theme);
				if (fill) {
					output.unshift({elementId:`slide-${slide.index+1}-background`,elementType:'shape',bounds:canvasBounds,shapeName:'rect',nativeShape:{geometry:'<a:prstGeom xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" prst="rect"><a:avLst/></a:prstGeom>',fill},...background ? {fill:background} : {}});
					outputElementCount++;
				}
			}
			const imageNotes = imageContracts.has(sourceSlide.slidePath) ? remapImageContract(imageContracts.get(sourceSlide.slidePath), elementNames, output) : void 0;
			if (imageNotes) for (const slot of JSON.parse(imageNotes).slots) {
				const image = output.find(element => element.elementId === slot.elementId);
				if (image) image.fit = { mode: slot.sourcePolicy === "native-graphic" ? "contain" : "cover" };
			}
			pages.set(pagePath, yamlText({
				pageType: slide.index === 0 ? "cover" : "content",
				background: background ?? {
					type: "solid",
					color: "#FFFFFF"
				},
				elements: output.map(markNativeShape).map(markSourceLayout),
				...imageNotes ? { notes: imageNotes } : {}
			}));
            sourceSlide.nodes=[];
            sourceSlide.background=undefined;
            files.slides.delete(sourceSlide.slidePath);
        };
        for(const sourceSlide of presentation.slides) {
            signal?.throwIfAborted();
            await convertSlide(sourceSlide);
            // Yield between pages so the host can deliver progress and collect
            // discarded DOM trees before another dense page is materialized.
            await new Promise(resolve=>setImmediate(resolve));
            signal?.throwIfAborted();
        }
		return {
			source: {
				entryName: "deck.pptd",
				manifest: yamlText({
					version: "v2",
					title: title || path.basename(fileName, path.extname(fileName)),
					size: [points(presentation.width), points(presentation.height)],
					theme: {
						colors: {
							primary: "#1F2937",
							accent: "#2563EB",
							text: "#111827",
							muted: "#6B7280",
							background: "#FFFFFF"
						},
						textStyles: {
							title: {
								fontFamily: "MiSans",
								fontSize: 36,
								bold: true,
								color: "$text"
							},
							body: {
								fontFamily: "MiSans",
								fontSize: 18,
								color: "$text"
							}
						}
					},
					pages: [...pages.keys()]
				}),
				pages,
				assets
			},
			slideCount: presentation.slides.length,
			sourceNodeCount,
			outputElementCount,
			extractedAssetCount: assets.size,
			diagnostics
		};
	} finally {
		restoreDomParser();
	}
}
//#endregion

export { convertPptxToPptd, yamlText, record };
