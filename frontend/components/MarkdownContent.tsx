import Markdown, { type Components } from 'react-markdown';

// LLM answers are untrusted: react-markdown never renders raw HTML and drops unsafe URLs.
// Images are not rendered either, so an answer cannot make the browser fetch remote content.
const DISALLOWED_ELEMENTS = ['img'];

const components: Components = {
  a: ({ node, ...props }) => {
    void node; // not a DOM attribute
    return (
      <a
        {...props}
        target="_blank"
        rel="noopener noreferrer"
        className="text-primary-700 underline hover:text-primary-800"
      />
    );
  },
};

interface MarkdownContentProps {
  children: string;
  className?: string;
}

/**
 * Renders an LLM answer written in Markdown (paragraphs, lists, emphasis, code).
 */
export default function MarkdownContent({ children, className = '' }: MarkdownContentProps) {
  return (
    <div
      className={`space-y-3 break-words text-sm leading-relaxed text-gray-800 [&_blockquote]:border-l-4 [&_blockquote]:border-gray-200 [&_blockquote]:pl-3 [&_code]:rounded [&_code]:bg-gray-100 [&_code]:px-1 [&_code]:font-mono [&_code]:text-xs [&_h1]:text-base [&_h1]:font-semibold [&_h2]:text-base [&_h2]:font-semibold [&_h3]:font-semibold [&_li]:mt-1 [&_ol]:list-decimal [&_ol]:pl-5 [&_pre]:overflow-x-auto [&_pre]:rounded [&_pre]:bg-gray-100 [&_pre]:p-3 [&_strong]:font-semibold [&_ul]:list-disc [&_ul]:pl-5 ${className}`}
    >
      <Markdown components={components} disallowedElements={DISALLOWED_ELEMENTS} unwrapDisallowed>
        {children}
      </Markdown>
    </div>
  );
}
