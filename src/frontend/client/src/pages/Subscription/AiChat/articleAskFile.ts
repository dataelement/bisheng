import type { Article } from "~/api/channels";

/** Labels of the small header written above the article body (localized by the caller). */
export interface ArticleAskFileLabels {
    source: string;
    link: string;
    publishedAt: string;
}

const BLOCK_END = /<\/(p|div|h[1-6]|li|tr|blockquote|section|article)>|<br\s*\/?>/gi;
/** Characters no common file system accepts in a name. */
const FORBIDDEN_IN_FILE_NAME = /[\\/:*?"<>|]/g;
const MAX_NAME_LENGTH = 60;

/** Readable text of an article body: block ends become line breaks, tags are dropped. */
function htmlToText(html: string): string {
    const doc = new DOMParser().parseFromString(html.replace(BLOCK_END, "$&\n"), "text/html");
    doc.querySelectorAll("script,style").forEach((el) => el.remove());
    return (doc.body.textContent ?? "")
        .replace(/[^\S\n]+/g, " ")
        .replace(/\n\s*\n\s*/g, "\n\n")
        .trim();
}

/**
 * The article as a Markdown file, for the 对话 handoff (see ~/components/Chat/chatAskHandoff):
 * the daily chat has no notion of "this channel article", but it does read attachments,
 * so the article travels as one. Title, source and link lead the file so the model can
 * name and cite what it is answering from.
 */
export function buildArticleAskFile(article: Article, labels: ArticleAskFileLabels): File {
    const body = article.content_html ? htmlToText(article.content_html) : (article.content ?? "").trim();
    const meta = [
        article.sourceName && `${labels.source}: ${article.sourceName}`,
        article.publishedAt && `${labels.publishedAt}: ${article.publishedAt}`,
        article.url && `${labels.link}: ${article.url}`,
    ].filter(Boolean);
    const text = [`# ${article.title}`, meta.join("\n"), body].filter(Boolean).join("\n\n");
    const baseName =
        article.title.replace(FORBIDDEN_IN_FILE_NAME, " ").replace(/\s+/g, " ").trim().slice(0, MAX_NAME_LENGTH) ||
        `article-${article.id}`;
    return new File([text], `${baseName}.md`, { type: "text/markdown" });
}
