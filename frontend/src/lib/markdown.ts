// Markdown der Antworten sicher rendern; Belege [n] werden zu Mini-Links auf die Stelle.
import { marked } from "marked";
import DOMPurify from "dompurify";

marked.setOptions({ gfm: true, breaks: true });

/** Belege [n] (auch [1][3]) vor dem Rendern in Mini-Links wandeln. */
function zitateVerlinken(text: string): string {
  return text.replace(/\[(\d{1,3})\]/g, (_, n: string) => `<a class="m-zitat" data-nr="${n}" href="#stelle-${n}" title="Stelle ${n}">${n}</a>`);
}

export function rendereMarkdown(text: string): string {
  const html = marked.parse(zitateVerlinken(text), { async: false }) as string;
  return DOMPurify.sanitize(html, { ADD_ATTR: ["data-nr", "target", "rel"] });
}
