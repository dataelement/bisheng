export type KunlianAutoOnboardingSetting = boolean | "inherit";

const TOP_LEVEL_KEY_RE = /^([A-Za-z0-9_.-]+)\s*:(.*)$/;

function getIndent(line: string): number {
  const match = line.match(/^[ \t]*/);
  return match ? match[0].length : 0;
}

function isIgnorableLine(line: string): boolean {
  const trimmed = line.trim();
  return trimmed.length === 0 || trimmed.startsWith("#");
}

function stripYamlComment(rawValue: string): string {
  const trimmed = rawValue.trim();
  if (!trimmed || trimmed.startsWith("#")) return "";
  if (trimmed.startsWith("'") || trimmed.startsWith('"')) {
    return trimmed;
  }
  const commentIndex = trimmed.indexOf("#");
  if (commentIndex === -1) return trimmed;
  return trimmed.slice(0, commentIndex).trim();
}

function parseAutoOnboardingScalar(rawValue: string): KunlianAutoOnboardingSetting {
  const clean = stripYamlComment(rawValue).toLowerCase();
  if (clean === "true") return true;
  if (clean === "false") return false;
  return "inherit";
}

interface KunlianBlockSpan {
  ssoSyncIndex: number;
  ssoSyncEndIndex: number;
  kunlianIndex: number;
  kunlianEndIndex: number;
  kunlianIndent: string;
  autoOnboardingIndex: number;
  childIndent: string;
}

function locateKunlianBlock(lines: string[]): KunlianBlockSpan {
  let ssoSyncIndex = -1;
  let ssoSyncEndIndex = lines.length;

  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i];
    if (isIgnorableLine(line) || getIndent(line) > 0) continue;
    const match = line.match(TOP_LEVEL_KEY_RE);
    if (!match) continue;
    if (ssoSyncIndex !== -1) {
      ssoSyncEndIndex = i;
      break;
    }
    if (match[1] === "sso_sync") {
      ssoSyncIndex = i;
    }
  }

  if (ssoSyncIndex === -1) {
    return {
      ssoSyncIndex: -1,
      ssoSyncEndIndex: lines.length,
      kunlianIndex: -1,
      kunlianEndIndex: lines.length,
      kunlianIndent: "  ",
      autoOnboardingIndex: -1,
      childIndent: "    ",
    };
  }

  let kunlianIndex = -1;
  let kunlianEndIndex = ssoSyncEndIndex;
  let kunlianIndent = "  ";
  let ssoChildIndentLen = -1;

  for (let i = ssoSyncIndex + 1; i < ssoSyncEndIndex; i += 1) {
    const line = lines[i];
    if (isIgnorableLine(line)) continue;
    const indentLen = getIndent(line);
    if (ssoChildIndentLen === -1) {
      ssoChildIndentLen = indentLen;
    }
    if (kunlianIndex !== -1 && indentLen <= kunlianIndent.length) {
      kunlianEndIndex = i;
      break;
    }
    if (indentLen === ssoChildIndentLen) {
      const match = line.trim().match(/^kunlian\s*:(.*)$/);
      if (match) {
        kunlianIndex = i;
        kunlianIndent = line.slice(0, indentLen);
      }
    }
  }

  let autoOnboardingIndex = -1;
  let childIndent = `${kunlianIndent}  `;
  if (kunlianIndex !== -1) {
    let firstChildIndentLen = -1;
    for (let i = kunlianIndex + 1; i < kunlianEndIndex; i += 1) {
      const line = lines[i];
      if (isIgnorableLine(line)) continue;
      const indentLen = getIndent(line);
      if (firstChildIndentLen === -1 && indentLen > kunlianIndent.length) {
        firstChildIndentLen = indentLen;
        childIndent = line.slice(0, indentLen);
      }
      if (
        firstChildIndentLen !== -1 &&
        indentLen === firstChildIndentLen &&
        /^auto_onboarding_enabled\s*:/.test(line.trim())
      ) {
        autoOnboardingIndex = i;
        break;
      }
    }
  }

  return {
    ssoSyncIndex,
    ssoSyncEndIndex,
    kunlianIndex,
    kunlianEndIndex,
    kunlianIndent,
    autoOnboardingIndex,
    childIndent,
  };
}

/**
 * Extract `sso_sync.kunlian.auto_onboarding_enabled` from raw YAML text.
 * Returns `"inherit"` when omitted or set to `null`/`~`, or explicit boolean otherwise.
 */
export function parseKunlianAutoOnboardingYaml(yamlText: string): KunlianAutoOnboardingSetting {
  if (!yamlText.trim()) return "inherit";
  const lines = yamlText.split(/\r?\n/);
  const span = locateKunlianBlock(lines);
  if (span.autoOnboardingIndex === -1) return "inherit";
  const line = lines[span.autoOnboardingIndex];
  const colonIdx = line.indexOf(":");
  if (colonIdx === -1) return "inherit";
  return parseAutoOnboardingScalar(line.slice(colonIdx + 1));
}

function serializeSetting(value: KunlianAutoOnboardingSetting): string {
  if (value === "inherit") return "null";
  return value ? "true" : "false";
}

function clearEmptyMappingInlineValue(line: string): string {
  const match = line.match(/^([ \t]*[A-Za-z0-9_.-]+\s*:)\s*(null|Null|NULL|~|\{\})\s*(#.*)?$/);
  if (!match) return line;
  return match[3] ? `${match[1]} ${match[3]}` : match[1];
}

/**
 * Return updated YAML text with `sso_sync.kunlian.auto_onboarding_enabled` set,
 * preserving unrelated sections and inline/block comments.
 */
export function updateKunlianAutoOnboardingYaml(
  yamlText: string,
  value: KunlianAutoOnboardingSetting,
): string {
  const eol = yamlText.includes("\r\n") ? "\r\n" : "\n";
  const trailingNewline = yamlText.endsWith("\n");
  const lines = yamlText ? yamlText.split(/\r?\n/) : [];
  if (trailingNewline && lines.length > 0 && lines[lines.length - 1] === "") {
    lines.pop();
  }

  const serialized = serializeSetting(value);
  const span = locateKunlianBlock(lines);

  if (span.autoOnboardingIndex !== -1) {
    const existing = lines[span.autoOnboardingIndex];
    const match = existing.match(/^([ \t]*auto_onboarding_enabled\s*:\s*)([^\r\n#]*?)([ \t]*(?:#.*)?)$/);
    if (match) {
      lines[span.autoOnboardingIndex] = `${match[1]}${serialized}${match[3]}`;
    } else {
      lines[span.autoOnboardingIndex] = `${span.childIndent}auto_onboarding_enabled: ${serialized}`;
    }
  } else if (span.kunlianIndex !== -1) {
    lines[span.kunlianIndex] = clearEmptyMappingInlineValue(lines[span.kunlianIndex]);
    lines.splice(span.kunlianEndIndex, 0, `${span.childIndent}auto_onboarding_enabled: ${serialized}`);
  } else if (span.ssoSyncIndex !== -1) {
    lines[span.ssoSyncIndex] = clearEmptyMappingInlineValue(lines[span.ssoSyncIndex]);
    lines.splice(
      span.ssoSyncEndIndex,
      0,
      `  kunlian:`,
      `    auto_onboarding_enabled: ${serialized}`,
    );
  } else {
    if (lines.length > 0 && lines[lines.length - 1].trim() !== "") {
      lines.push("");
    }
    lines.push("sso_sync:", "  kunlian:", `    auto_onboarding_enabled: ${serialized}`);
  }

  const result = lines.join(eol);
  return trailingNewline || result.length > 0 ? `${result}${eol}` : "";
}
