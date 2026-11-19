import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

// Keep generated text as React nodes. Raw HTML is never interpreted, and images
// are represented by their descriptions instead of loading remote resources.
const components: Components = {
  p: ({ children }) => <p className="whitespace-pre-wrap">{children}</p>,
  a: ({ href, children }) => href
    ? <a href={href} target="_blank" rel="noopener noreferrer" className="focus-ring rounded-sm font-medium text-lime underline decoration-lime/40 underline-offset-2 hover:decoration-lime">{children}</a>
    : <span>{children}</span>,
  img: ({ alt }) => <span className="text-muted">{alt || "Image omitted"}</span>,
  h1: ({ children }) => <h3 className="font-semibold">{children}</h3>,
  h2: ({ children }) => <h3 className="font-semibold">{children}</h3>,
  h3: ({ children }) => <h3 className="font-semibold">{children}</h3>,
  h4: ({ children }) => <h4 className="font-semibold">{children}</h4>,
  h5: ({ children }) => <h4 className="font-semibold">{children}</h4>,
  h6: ({ children }) => <h4 className="font-semibold">{children}</h4>,
  ul: ({ children }) => <ul className="list-disc space-y-1 pl-5">{children}</ul>,
  ol: ({ children, start }) => <ol start={start} className="list-decimal space-y-1 pl-5">{children}</ol>,
  blockquote: ({ children }) => <blockquote className="space-y-2 border-l-2 border-line pl-3 text-muted">{children}</blockquote>,
  pre: ({ children }) => <pre role="region" aria-label="Code sample" tabIndex={0} className="focus-ring min-w-0 max-w-full overflow-x-auto overscroll-x-contain rounded-lg border border-line bg-raised p-3 text-sm">{children}</pre>,
  code: ({ children }) => <code className="rounded bg-raised px-1 py-0.5 font-mono text-[.9em]">{children}</code>,
  table: ({ children }) => <div role="region" aria-label="Response table" tabIndex={0} className="focus-ring min-w-0 max-w-full overflow-x-auto overscroll-x-contain rounded-lg border border-line"><table className="w-full min-w-[24rem] border-collapse text-left text-sm">{children}</table></div>,
  th: ({ children }) => <th className="min-w-[10rem] border-b border-line bg-raised px-3 py-2 font-semibold [overflow-wrap:anywhere]">{children}</th>,
  td: ({ children }) => <td className="min-w-[10rem] border-b border-line px-3 py-2 align-top [overflow-wrap:anywhere]">{children}</td>,
  hr: () => <hr className="border-line"/>,
};

export function MessageContent({ content, streaming = false }: { content: string; streaming?: boolean }) {
  return <div className={`min-w-0 space-y-3 text-[15px] leading-6 text-cream [overflow-wrap:anywhere] ${streaming ? "token-caret" : ""}`}>
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>{content}</ReactMarkdown>
  </div>;
}
